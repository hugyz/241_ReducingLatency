"""
WARZONE — Multiplayer Top-Down Shooter
=======================================
Run one instance per player. Each player connects through the edge node.

Usage:
    python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --color 0
    python arena_game.py --client-id p2 --edge 127.0.0.1:8000 --color 1

Controls:
    WASD        — Move
    Mouse       — Aim
    LMB         — Shoot
    R           — Reload
    1-7         — Switch weapon
    E           — Pick up weapon crate
    ESC         — Quit

Multiplayer protocol:
    PREDICTION payload carries: x, y, angle, hp, weapon_idx, action
    action = None | {type: "shoot", bx, by, angle, weapon_idx, spread_seed}
           | {type: "hit",   target_id, damage}
           | {type: "dead"}
           | {type: "pickup", crate_idx}
"""

import argparse
import math
import random
import sys
import threading
import time as _time

import pandas as pd
import pygame

# ── Try to import networking from python-client/ ───────────────────────────────
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python-client"))
from net import UdpTransport, choose_best_endpoint
from protocol import MessageType, create_message, decode_message

# ══════════════════════════════════════════════════════════════════════════════
#  ARGUMENT PARSING  (done before pygame init so --help works cleanly)
# ══════════════════════════════════════════════════════════════════════════════
def parse_args():
    ap = argparse.ArgumentParser(description="WARZONE multiplayer client")
    ap.add_argument("--main", default=None, help="main server host:port (for discovery)")
    ap.add_argument("--client-id", default="p1", help="unique player id")
    ap.add_argument("--edge",      default="127.0.0.1:8000", help="edge node host:port")
    ap.add_argument("--region", default="A", help="client region (A, B, etc) used for latency simulation")
    ap.add_argument("--color",     type=int, default=0, help="player color index 0-8")
    ap.add_argument("--map-seed",  type=int, default=12345, help="shared map seed (must match all players)")
    ap.add_argument("--terrain",   default="forest",
                    choices=["forest","desert","urban","snow","volcano"],
                    help="map terrain (must match all players)")
    ap.add_argument("--ai", action="store_true", help="enable AI enemies")
    return ap.parse_args()

# ══════════════════════════════════════════════════════════════════════════════
#  PYGAME INIT
# ══════════════════════════════════════════════════════════════════════════════
pygame.init()

W, H = 1024, 768
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("WARZONE  — MULTIPLAYER")
clock = pygame.time.Clock()

TILE  = 48
COLS  = 52
ROWS  = 40
MAP_W = COLS * TILE
MAP_H = ROWS * TILE

# ── Colours ───────────────────────────────────────────────────────────────────
BG        = (14, 22, 12)
FLASH_C   = (255, 248, 180)
BLOOD_C   = (105, 6, 6)
HUD_G     = (65, 200, 75)
HUD_Y     = (200, 180, 40)
HUD_R     = (195, 50, 50)
HUD_W     = (220, 220, 205)
CRATE_COL = (180, 150, 50)
CRATE_HL  = (220, 200, 80)

# ── Fonts ─────────────────────────────────────────────────────────────────────
fnt_s   = pygame.font.SysFont("monospace", 12)
fnt_m   = pygame.font.SysFont("monospace", 16, bold=True)
fnt_l   = pygame.font.SysFont("monospace", 34, bold=True)
fnt_xl  = pygame.font.SysFont("monospace", 52, bold=True)
fnt_ti  = pygame.font.SysFont("monospace", 64, bold=True)
fnt_btn = pygame.font.SysFont("monospace", 20, bold=True)

# ══════════════════════════════════════════════════════════════════════════════
#  TERRAIN THEMES
# ══════════════════════════════════════════════════════════════════════════════
TERRAINS = {
    "forest": {
        "name": "FOREST", "ground_a": (36,50,28), "ground_b": (42,57,33),
        "wall_lit": (72,65,48), "wall_drk": (42,38,28), "wall_hl": (92,84,62),
        "fog": (10,18,8), "bg": (14,22,12), "accent": (55,140,55),
        "desc": "Dense woodland — tight corridors",
    },
    "desert": {
        "name": "DESERT", "ground_a": (75,65,42), "ground_b": (82,72,48),
        "wall_lit": (110,95,65), "wall_drk": (70,58,38), "wall_hl": (140,125,90),
        "fog": (25,20,10), "bg": (30,25,15), "accent": (200,170,80),
        "desc": "Open sands — long sightlines",
    },
    "urban": {
        "name": "URBAN", "ground_a": (48,48,52), "ground_b": (55,55,60),
        "wall_lit": (85,82,90), "wall_drk": (45,43,50), "wall_hl": (110,105,120),
        "fog": (12,12,18), "bg": (18,18,25), "accent": (100,140,200),
        "desc": "City ruins — lots of cover",
    },
    "snow": {
        "name": "SNOW", "ground_a": (170,175,180), "ground_b": (160,165,172),
        "wall_lit": (120,125,135), "wall_drk": (80,82,92), "wall_hl": (200,205,215),
        "fog": (40,42,50), "bg": (55,58,68), "accent": (130,180,220),
        "desc": "Frozen tundra — reduced fog",
    },
    "volcano": {
        "name": "VOLCANO", "ground_a": (40,22,18), "ground_b": (50,28,22),
        "wall_lit": (65,35,25), "wall_drk": (35,18,12), "wall_hl": (95,50,30),
        "fog": (18,8,5), "bg": (22,10,8), "accent": (220,90,30),
        "desc": "Lava fields — narrow paths",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
#  WEAPONS
# ══════════════════════════════════════════════════════════════════════════════
WEAPONS = [
    {"name":"PISTOL",      "fire_rate":0.25, "speed":12, "damage":12, "spread":0.05,
     "max_ammo":999, "count":1, "b_size":3, "b_color":(255,230,70),  "special":"none",      "slot":1},
    {"name":"SMG",         "fire_rate":0.07, "speed":13, "damage":10, "spread":0.12,
     "max_ammo":45,  "count":1, "b_size":3, "b_color":(255,200,50),  "special":"none",      "slot":2},
    {"name":"SHOTGUN",     "fire_rate":0.55, "speed":11, "damage":8,  "spread":0.25,
     "max_ammo":16,  "count":7, "b_size":3, "b_color":(255,180,60),  "special":"none",      "slot":3},
    {"name":"RIFLE",       "fire_rate":0.35, "speed":20, "damage":35, "spread":0.02,
     "max_ammo":20,  "count":1, "b_size":4, "b_color":(200,255,200), "special":"pierce",    "slot":4},
    {"name":"FLAMETHROWER","fire_rate":0.04, "speed":7,  "damage":5,  "spread":0.35,
     "max_ammo":100, "count":2, "b_size":5, "b_color":(255,120,20),  "special":"flame",     "slot":5},
    {"name":"GRENADE L.",  "fire_rate":0.80, "speed":8,  "damage":50, "spread":0.06,
     "max_ammo":10,  "count":1, "b_size":6, "b_color":(120,220,80),  "special":"explode",   "slot":6},
    {"name":"RAILGUN",     "fire_rate":1.20, "speed":40, "damage":100,"spread":0.0,
     "max_ammo":5,   "count":1, "b_size":5, "b_color":(80,200,255),  "special":"rail",      "slot":7},
]

# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER COLORS  (index shared between all clients via --color arg)
# ══════════════════════════════════════════════════════════════════════════════
PLAYER_COLORS = [
    ("Green",  (85,175,85),   (50,115,50)),
    ("Blue",   (70,130,210),  (40,80,150)),
    ("Red",    (210,75,65),   (140,40,30)),
    ("Purple", (160,90,200),  (100,50,140)),
    ("Orange", (220,150,50),  (160,100,20)),
    ("Cyan",   (60,200,200),  (30,140,140)),
    ("Yellow", (220,210,60),  (160,150,20)),
    ("Pink",   (220,110,160), (160,65,110)),
    ("White",  (210,210,210), (150,150,150)),
]

# ══════════════════════════════════════════════════════════════════════════════
#  MAP
# ══════════════════════════════════════════════════════════════════════════════
MAP         = None
CUR_TERRAIN = None

def gen_map(terrain_key, seed=12345):
    random.seed(seed)
    g = [[0]*COLS for _ in range(ROWS)]
    for r in range(ROWS): g[r][0] = g[r][COLS-1] = 1
    for c in range(COLS): g[0][c] = g[ROWS-1][c] = 1

    if terrain_key == "forest":
        for _ in range(180):
            r,c = random.randint(2,ROWS-3), random.randint(2,COLS-3)
            for dr in range(random.randint(1,3)):
                for dc in range(random.randint(1,3)):
                    nr,nc = r+dr,c+dc
                    if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=1
    elif terrain_key == "desert":
        for _ in range(60):
            r,c = random.randint(2,ROWS-3), random.randint(2,COLS-3)
            for dr in range(random.randint(1,2)):
                for dc in range(random.randint(2,6)):
                    nr,nc = r+dr,c+dc
                    if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=1
    elif terrain_key == "urban":
        for _ in range(30):
            r,c = random.randint(2,ROWS-6), random.randint(2,COLS-6)
            bh,bw = random.randint(3,6), random.randint(3,7)
            for dr in range(bh):
                for dc in range(bw):
                    nr,nc = r+dr,c+dc
                    if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=1
            side = random.randint(0,3)
            if side==0 and r>1:
                mid=c+bw//2
                if 1<=mid<COLS-1: g[r][mid]=0
            elif side==1 and r+bh<ROWS-1:
                mid=c+bw//2
                if 1<=mid<COLS-1: g[r+bh-1][mid]=0
            elif side==2 and c>1:
                mid=r+bh//2
                if 1<=mid<ROWS-1: g[mid][c]=0
            elif c+bw<COLS-1:
                mid=r+bh//2
                if 1<=mid<ROWS-1: g[mid][c+bw-1]=0
    elif terrain_key == "snow":
        for _ in range(110):
            r,c = random.randint(2,ROWS-3), random.randint(2,COLS-3)
            for dr in range(random.randint(1,3)):
                for dc in range(random.randint(1,4)):
                    nr,nc = r+dr,c+dc
                    if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=1
    elif terrain_key == "volcano":
        for r in range(1,ROWS-1):
            for c in range(1,COLS-1): g[r][c]=1
        for _ in range(35):
            px,py = random.randint(2,COLS-3), random.randint(2,ROWS-3)
            for _ in range(random.randint(20,60)):
                if 1<=py<ROWS-1 and 1<=px<COLS-1:
                    g[py][px]=0
                    for dr in range(-1,2):
                        for dc in range(-1,2):
                            nr,nc = py+dr,px+dc
                            if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=0
                d=random.randint(0,3)
                if d==0: px+=1
                elif d==1: px-=1
                elif d==2: py+=1
                else: py-=1
    else:
        for _ in range(120):
            r,c = random.randint(2,ROWS-3), random.randint(2,COLS-3)
            for dr in range(random.randint(1,3)):
                for dc in range(random.randint(1,4)):
                    nr,nc = r+dr,c+dc
                    if 1<=nr<ROWS-1 and 1<=nc<COLS-1: g[nr][nc]=1

    for r in range(1,7):
        for c in range(1,8): g[r][c]=0
    return g

def is_wall(r,c):
    if not (0<=r<ROWS and 0<=c<COLS): return True
    return MAP[r][c]==1

def rect_hits_wall(rect, margin=3):
    inner = pygame.Rect(rect.x+margin, rect.y+margin, rect.w-margin*2, rect.h-margin*2)
    for r in range(inner.top//TILE, inner.bottom//TILE+1):
        for c in range(inner.left//TILE, inner.right//TILE+1):
            if is_wall(r,c): return True
    return False

_ground = _wall_surf = None

def bake_map():
    global _ground, _wall_surf
    t = TERRAINS[CUR_TERRAIN]
    _ground = pygame.Surface((MAP_W, MAP_H))
    for r in range(ROWS):
        for c in range(COLS):
            col = t["ground_a"] if (r+c)%2==0 else t["ground_b"]
            _ground.fill(col, (c*TILE, r*TILE, TILE, TILE))
    _wall_surf = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
    _wall_surf.fill((0,0,0,0))
    for r in range(ROWS):
        for c in range(COLS):
            if MAP[r][c]==1:
                rx,ry = c*TILE,r*TILE
                pygame.draw.rect(_wall_surf, t["wall_lit"], (rx,ry,TILE,TILE))
                pygame.draw.rect(_wall_surf, t["wall_drk"], (rx,ry,TILE,TILE), 2)
                pygame.draw.line(_wall_surf, t["wall_hl"], (rx,ry), (rx+TILE,ry), 2)

def draw_map(surface, cx, cy):
    surface.blit(_ground, (0,0), (int(cx),int(cy),W,H))
    surface.blit(_wall_surf, (-int(cx),-int(cy)))

# ══════════════════════════════════════════════════════════════════════════════
#  CAMERA
# ══════════════════════════════════════════════════════════════════════════════
cam = pygame.Vector2(0.0, 0.0)

def update_cam(px,py):
    cam.x += (px-W/2 - cam.x)*0.10
    cam.y += (py-H/2 - cam.y)*0.10
    cam.x = max(0, min(MAP_W-W, cam.x))
    cam.y = max(0, min(MAP_H-H, cam.y))

def ws(wx,wy): return wx-cam.x, wy-cam.y

# ══════════════════════════════════════════════════════════════════════════════
#  PARTICLES
# ══════════════════════════════════════════════════════════════════════════════
particles = []

def spawn_blood(x,y,n=8):
    for _ in range(n):
        a=random.uniform(0,math.tau); s=random.uniform(1.0,3.5); life=random.randint(18,45)
        particles.append([x,y,math.cos(a)*s,math.sin(a)*s,life,life,random.randint(2,5),BLOOD_C])

def spawn_flash(x,y,angle):
    for _ in range(7):
        a=angle+random.uniform(-0.35,0.35); s=random.uniform(2,6); life=random.randint(3,8)
        particles.append([x,y,math.cos(a)*s,math.sin(a)*s,life,life,random.randint(2,4),FLASH_C])

def spawn_shell(x,y,angle):
    a=angle+math.pi/2+random.uniform(-0.3,0.3); s=random.uniform(1.5,3); life=random.randint(20,40)
    particles.append([x,y,math.cos(a)*s,math.sin(a)*s,life,life,2,(180,150,40)])

def spawn_explosion(x,y):
    for _ in range(40):
        a=random.uniform(0,math.tau); s=random.uniform(1.5,6.0); life=random.randint(12,35)
        col=random.choice([(255,200,40),(255,140,20),(255,80,10),(200,60,10)])
        particles.append([x,y,math.cos(a)*s,math.sin(a)*s,life,life,random.randint(3,8),col])

def update_particles():
    dead=[]
    for p in particles:
        p[0]+=p[2]; p[1]+=p[3]; p[2]*=0.84; p[3]*=0.84; p[4]-=1
        if p[4]<=0: dead.append(p)
    for d in dead: particles.remove(d)

def draw_particles(surface):
    for p in particles:
        sx,sy=ws(p[0],p[1])
        if -20<sx<W+20 and -20<sy<H+20:
            t=max(p[4]/p[5],0.01); r=max(1,int(p[6]*t))
            c=tuple(max(0,min(255,int(v*t))) for v in p[7])
            pygame.draw.circle(surface,c,(int(sx),int(sy)),r)

# ══════════════════════════════════════════════════════════════════════════════
#  BULLET  (local simulation — same for local and remote shots)
# ══════════════════════════════════════════════════════════════════════════════
class Bullet:
    def __init__(self, x, y, angle, owner_id, weapon, is_local=True):
        self.x, self.y = x, y
        self.vx = math.cos(angle)*weapon["speed"]
        self.vy = math.sin(angle)*weapon["speed"]
        self.owner_id  = owner_id   # client_id string
        self.is_local  = is_local   # True = fired by this client
        self.alive     = True
        self.trail     = []
        self.damage    = weapon["damage"]
        self.b_size    = weapon["b_size"]
        self.b_color   = weapon["b_color"]
        self.special   = weapon["special"]
        self.life      = 180
        self.pierced   = 0

    def update(self):
        self.trail.append((self.x,self.y))
        if len(self.trail)>6: self.trail.pop(0)
        self.x+=self.vx; self.y+=self.vy; self.life-=1
        if self.life<=0: self.alive=False
        if self.special=="flame":
            self.vx*=0.94; self.vy*=0.94
            if abs(self.vx)+abs(self.vy)<1.5: self.alive=False
        if is_wall(int(self.y//TILE), int(self.x//TILE)):
            if self.special not in ("rail",): self.alive=False

    def draw(self, surface):
        col = self.b_color
        for i,(tx,ty) in enumerate(self.trail):
            t=(i+1)/len(self.trail); r=max(1,int(self.b_size*t))
            c=tuple(int(v*t) for v in col)
            sx,sy=ws(tx,ty)
            if -20<sx<W+20 and -20<sy<H+20:
                pygame.draw.circle(surface,c,(int(sx),int(sy)),r)
        sx,sy=ws(self.x,self.y)
        if -20<sx<W+20 and -20<sy<H+20:
            pygame.draw.circle(surface,col,(int(sx),int(sy)),self.b_size)
            if self.special=="flame":
                s=pygame.Surface((self.b_size*4,self.b_size*4),pygame.SRCALPHA)
                pygame.draw.circle(s,(*col[:3],60),(self.b_size*2,self.b_size*2),self.b_size*2)
                surface.blit(s,(int(sx)-self.b_size*2,int(sy)-self.b_size*2))

# ══════════════════════════════════════════════════════════════════════════════
#  WEAPON CRATE
# ══════════════════════════════════════════════════════════════════════════════
class WeaponCrate:
    def __init__(self,x,y,weapon_idx):
        self.x=x; self.y=y; self.weapon_idx=weapon_idx
        self.alive=True; self.bob=random.uniform(0,math.tau)
    def update(self): self.bob+=0.05
    def draw(self,surface):
        sx,sy=ws(self.x,self.y)
        if not(-30<sx<W+30 and -30<sy<H+30): return
        by=sy+math.sin(self.bob)*3
        pygame.draw.rect(surface,CRATE_COL,(int(sx)-11,int(by)-8,22,18))
        pygame.draw.rect(surface,CRATE_HL, (int(sx)-11,int(by)-8,22,18),2)
        label=fnt_s.render(WEAPONS[self.weapon_idx]["name"],True,(255,255,200))
        surface.blit(label,(int(sx)-label.get_width()//2,int(by)-22))

# ══════════════════════════════════════════════════════════════════════════════
#  LOCAL PLAYER
# ══════════════════════════════════════════════════════════════════════════════
class Player:
    RADIUS=13; ACCEL=750.0; FRICTION=8.5; MAX_SPEED=290.0; MAX_HP=100

    def __init__(self, color_idx=0):
        self.x=TILE*3.0; self.y=TILE*3.0
        self.vx=self.vy=self.ax=self.ay=0.0
        self.angle=0.0; self.hp=self.MAX_HP; self.alive=True
        self.hurt_flash=0.0; self.flash_t=0.0
        self.died_x=None; self.died_y=None
        self.col      = PLAYER_COLORS[color_idx][1]
        self.col_dark = PLAYER_COLORS[color_idx][2]
        self.weapons  = [(0, WEAPONS[0]["max_ammo"])]
        self.cur_weapon=0; self.fire_cd=0.0

    @property
    def weapon(self): return WEAPONS[self.weapons[self.cur_weapon][0]]
    @property
    def ammo(self): return self.weapons[self.cur_weapon][1]
    @ammo.setter
    def ammo(self,v):
        idx,_=self.weapons[self.cur_weapon]
        self.weapons[self.cur_weapon]=(idx,v)

    def give_weapon(self,weapon_idx):
        for i,(wi,_) in enumerate(self.weapons):
            if wi==weapon_idx:
                self.weapons[i]=(wi,WEAPONS[wi]["max_ammo"]); self.cur_weapon=i; return
        self.weapons.append((weapon_idx,WEAPONS[weapon_idx]["max_ammo"]))
        self.cur_weapon=len(self.weapons)-1

    def switch_weapon(self,slot):
        for i,(wi,_) in enumerate(self.weapons):
            if WEAPONS[wi]["slot"]==slot: self.cur_weapon=i; return

    def update(self,dt,keys,mx,my):
        ix=float(keys[pygame.K_d]-keys[pygame.K_a])
        iy=float(keys[pygame.K_s]-keys[pygame.K_w])
        mag=math.hypot(ix,iy)
        if mag: ix/=mag; iy/=mag
        self.ax=ix*self.ACCEL; self.ay=iy*self.ACCEL
        self.vx+=self.ax*dt; self.vy+=self.ay*dt
        self.vx-=self.vx*self.FRICTION*dt; self.vy-=self.vy*self.FRICTION*dt
        spd=math.hypot(self.vx,self.vy)
        if spd>self.MAX_SPEED: self.vx=self.vx/spd*self.MAX_SPEED; self.vy=self.vy/spd*self.MAX_SPEED

        nx=self.x+self.vx*dt
        if not rect_hits_wall(pygame.Rect(nx-self.RADIUS,self.y-self.RADIUS,self.RADIUS*2,self.RADIUS*2)):
            self.x=nx
        else: self.vx=0
        ny=self.y+self.vy*dt
        if not rect_hits_wall(pygame.Rect(self.x-self.RADIUS,ny-self.RADIUS,self.RADIUS*2,self.RADIUS*2)):
            self.y=ny
        else: self.vy=0

        sx,sy=ws(self.x,self.y)
        self.angle=math.atan2(my-sy,mx-sx)
        self.fire_cd=max(0.0,self.fire_cd-dt)
        self.flash_t=max(0.0,self.flash_t-dt)
        self.hurt_flash=max(0.0,self.hurt_flash-dt)

    def shoot(self, bullets):
        """Returns list of shot dicts to be networked, or empty list."""
        w=self.weapon
        shots=[]
        if self.fire_cd<=0 and self.ammo>0:
            seed=random.randint(0,999999)
            rng=random.Random(seed)
            for _ in range(w["count"]):
                spread=rng.uniform(-w["spread"],w["spread"])
                bx=self.x+math.cos(self.angle)*(self.RADIUS+5)
                by=self.y+math.sin(self.angle)*(self.RADIUS+5)
                bullets.append(Bullet(bx,by,self.angle+spread,"local",w,is_local=True))
            self.fire_cd=w["fire_rate"]; self.ammo-=1
            self.flash_t=0.06
            spawn_flash(bx,by,self.angle); spawn_shell(bx,by,self.angle)
            shots.append({"type":"shoot","bx":bx,"by":by,
                          "angle":self.angle,"weapon_idx":self.weapons[self.cur_weapon][0],
                          "spread_seed":seed})
        return shots

    def reload(self):
        idx,_=self.weapons[self.cur_weapon]
        self.weapons[self.cur_weapon]=(idx,WEAPONS[idx]["max_ammo"])

    def take_hit(self,dmg):
        self.hp-=dmg; self.hurt_flash=0.18; spawn_blood(self.x,self.y,5)
        if self.hp<=0:
            self.hp=0; self.alive=False
            self.died_x=self.x; self.died_y=self.y
            spawn_blood(self.x,self.y,20)

    def draw(self,surface):
        sx,sy=ws(self.x,self.y)
        if self.flash_t>0:
            fx=sx+math.cos(self.angle)*(self.RADIUS+12)
            fy=sy+math.sin(self.angle)*(self.RADIUS+12)
            pygame.draw.circle(surface,FLASH_C,(int(fx),int(fy)),int(9*self.flash_t/0.06))
        pygame.draw.circle(surface,(8,16,6),(int(sx)+3,int(sy)+4),self.RADIUS+2)
        pygame.draw.circle(surface,self.col_dark,(int(sx),int(sy)),self.RADIUS)
        pygame.draw.circle(surface,self.col,(int(sx),int(sy)),self.RADIUS-2)
        hl=tuple(min(255,c+60) for c in self.col)
        pygame.draw.circle(surface,hl,(int(sx),int(sy)),self.RADIUS-2,1)
        ex=sx+math.cos(self.angle)*(self.RADIUS+10)
        ey=sy+math.sin(self.angle)*(self.RADIUS+10)
        pygame.draw.line(surface,(200,195,170),(int(sx),int(sy)),(int(ex),int(ey)),5)
        pygame.draw.line(surface,(230,225,200),(int(sx),int(sy)),(int(ex),int(ey)),2)

# ══════════════════════════════════════════════════════════════════════════════
#  REMOTE PLAYER  (rendered from network state)
# ══════════════════════════════════════════════════════════════════════════════
class RemotePlayer:
    RADIUS=13; MAX_HP=100

    def __init__(self, client_id, color_idx):
        self.client_id  = client_id
        self.x=TILE*3.0; self.y=TILE*3.0
        self.angle=0.0; self.hp=self.MAX_HP; self.alive=True
        self.col      = PLAYER_COLORS[color_idx % len(PLAYER_COLORS)][1]
        self.col_dark = PLAYER_COLORS[color_idx % len(PLAYER_COLORS)][2]
        self.latency_ms = 0
        self.last_timestamp_ms = 0   # ← add this
        self.last_seen  = _time.time()

    def apply_state(self, payload, latency_ms, timestamp_ms):
        # Reject stale updates
        if timestamp_ms <= self.last_timestamp_ms:
            return
        self.last_timestamp_ms = timestamp_ms

        state = payload.get("state", {})
        self.x        = float(state.get("x", self.x))
        self.y        = float(state.get("y", self.y))
        self.angle    = float(state.get("angle", self.angle))
        self.hp       = int(state.get("hp", self.hp))
        self.alive    = self.hp > 0
        self.latency_ms = latency_ms
        self.last_seen  = _time.time()

    def draw(self, surface):
        if not self.alive:
            sx,sy=ws(self.x,self.y)
            if -20<sx<W+20 and -20<sy<H+20:
                r=self.RADIUS
                pygame.draw.circle(surface,(80,20,20),(int(sx),int(sy)),r)
                pygame.draw.line(surface,(160,40,40),(int(sx)-r+4,int(sy)-r+4),(int(sx)+r-4,int(sy)+r-4),3)
                pygame.draw.line(surface,(160,40,40),(int(sx)+r-4,int(sy)-r+4),(int(sx)-r+4,int(sy)+r-4),3)
                tag=fnt_s.render(f"{self.client_id} [KIA]",True,(160,60,60))
                surface.blit(tag,(int(sx)-tag.get_width()//2,int(sy)-r-22))
            return
        sx,sy=ws(self.x,self.y)
        if not(-20<sx<W+20 and -20<sy<H+20): return

        pygame.draw.circle(surface,(8,16,6),(int(sx)+3,int(sy)+4),self.RADIUS+2)
        pygame.draw.circle(surface,self.col_dark,(int(sx),int(sy)),self.RADIUS)
        pygame.draw.circle(surface,self.col,(int(sx),int(sy)),self.RADIUS-2)
        hl=tuple(min(255,c+60) for c in self.col)
        pygame.draw.circle(surface,hl,(int(sx),int(sy)),self.RADIUS-2,1)

        ex=sx+math.cos(self.angle)*(self.RADIUS+10)
        ey=sy+math.sin(self.angle)*(self.RADIUS+10)
        pygame.draw.line(surface,(200,195,170),(int(sx),int(sy)),(int(ex),int(ey)),5)

        # HP bar
        bw=26; ratio=self.hp/self.MAX_HP
        pygame.draw.rect(surface,(50,10,10),(int(sx)-bw//2,int(sy)-self.RADIUS-9,bw,4))
        pygame.draw.rect(surface,HUD_R,    (int(sx)-bw//2,int(sy)-self.RADIUS-9,int(bw*ratio),4))

        # Name + latency tag
        tag=fnt_s.render(f"{self.client_id} {self.latency_ms}ms",True,(220,220,180))
        surface.blit(tag,(int(sx)-tag.get_width()//2,int(sy)-self.RADIUS-22))

# ══════════════════════════════════════════════════════════════════════════════
#  AI ENEMY  (local-only, same as original)
# ══════════════════════════════════════════════════════════════════════════════
class Enemy:
    RADIUS=11; ACCEL=340.0; FRICTION=7.5; MAX_SPEED=115.0; MAX_HP=40; SIGHT_R=300.0

    def __init__(self,x,y):
        self.x=x; self.y=y; self.vx=self.vy=0.0; self.angle=0.0
        self.hp=self.MAX_HP; self.alive=True; self.state="patrol"
        self.patrol_timer=0.0; self.patrol_angle=random.uniform(0,math.tau); self.alert=0.0
        self.fire_rate=random.uniform(1.2,2.2); self.fire_cd=random.uniform(0,self.fire_rate)
        self.last_timestamp_ms = 0

    def update(self,dt,player,bullets):
        dx=player.x-self.x; dy=player.y-self.y; d=math.hypot(dx,dy) or 1
        self.angle=math.atan2(dy,dx)
        if d<self.SIGHT_R: self.state="shoot" if d<120 else "chase"; self.alert=0.4
        else: self.state="patrol"
        if self.state=="chase": ax=(dx/d)*self.ACCEL; ay=(dy/d)*self.ACCEL
        elif self.state=="patrol":
            self.patrol_timer-=dt
            if self.patrol_timer<=0:
                self.patrol_angle=random.uniform(0,math.tau); self.patrol_timer=random.uniform(1.5,4.0)
            ax=math.cos(self.patrol_angle)*120; ay=math.sin(self.patrol_angle)*120
        else: ax=ay=0.0
        self.vx+=ax*dt; self.vy+=ay*dt
        self.vx-=self.vx*self.FRICTION*dt; self.vy-=self.vy*self.FRICTION*dt
        spd=math.hypot(self.vx,self.vy)
        if spd>self.MAX_SPEED: self.vx=self.vx/spd*self.MAX_SPEED; self.vy=self.vy/spd*self.MAX_SPEED
        nx=self.x+self.vx*dt
        if not rect_hits_wall(pygame.Rect(nx-self.RADIUS,self.y-self.RADIUS,self.RADIUS*2,self.RADIUS*2)):
            self.x=nx
        else: self.vx*=-0.4; self.patrol_angle+=math.pi+random.uniform(-0.5,0.5)
        ny=self.y+self.vy*dt
        if not rect_hits_wall(pygame.Rect(self.x-self.RADIUS,ny-self.RADIUS,self.RADIUS*2,self.RADIUS*2)):
            self.y=ny
        else: self.vy*=-0.4; self.patrol_angle+=math.pi+random.uniform(-0.5,0.5)
        self.fire_cd=max(0,self.fire_cd-dt); self.alert=max(0,self.alert-dt)
        if self.state=="shoot" and self.fire_cd<=0:
            spread=random.uniform(-0.10,0.10)
            bx=self.x+math.cos(self.angle)*(self.RADIUS+4)
            by=self.y+math.sin(self.angle)*(self.RADIUS+4)
            bullets.append(Bullet(bx,by,self.angle+spread,"enemy",WEAPONS[0],is_local=False))
            self.fire_cd=self.fire_rate; spawn_flash(bx,by,self.angle)

    def take_hit(self,dmg):
        self.hp-=dmg; spawn_blood(self.x,self.y,7)
        if self.hp<=0: self.alive=False; spawn_blood(self.x,self.y,18)

    def draw(self,surface):
        sx,sy=ws(self.x,self.y)
        if not(-20<sx<W+20 and -20<sy<H+20): return
        if self.alert>0 and self.state!="patrol":
            t=self.alert/0.4; col=tuple(int(v*t) for v in HUD_Y)
            pts=[(sx,sy-self.RADIUS-14),(sx+6,sy-self.RADIUS-8),(sx,sy-self.RADIUS-2),(sx-6,sy-self.RADIUS-8)]
            pygame.draw.polygon(surface,col,pts)
        pygame.draw.circle(surface,(8,16,6),(int(sx)+3,int(sy)+4),self.RADIUS+1)
        pygame.draw.circle(surface,(120,35,28),(int(sx),int(sy)),self.RADIUS)
        pygame.draw.circle(surface,(190,62,52),(int(sx),int(sy)),self.RADIUS-2)
        ex=sx+math.cos(self.angle)*(self.RADIUS+8); ey=sy+math.sin(self.angle)*(self.RADIUS+8)
        pygame.draw.line(surface,(175,155,130),(int(sx),int(sy)),(int(ex),int(ey)),4)
        bw=26; ratio=self.hp/self.MAX_HP
        pygame.draw.rect(surface,(50,10,10),(int(sx)-bw//2,int(sy)-self.RADIUS-9,bw,4))
        pygame.draw.rect(surface,HUD_R,(int(sx)-bw//2,int(sy)-self.RADIUS-9,int(bw*ratio),4))

# ══════════════════════════════════════════════════════════════════════════════
#  FOG OF WAR
# ══════════════════════════════════════════════════════════════════════════════
FOG_R=220
_fog_surf=pygame.Surface((W,H),pygame.SRCALPHA)

def draw_fog(player):
    t=TERRAINS[CUR_TERRAIN]; fog_col=t["fog"]
    _fog_surf.fill((*fog_col,242))
    sx,sy=int(ws(player.x,player.y)[0]),int(ws(player.x,player.y)[1])
    r=FOG_R
    if CUR_TERRAIN=="snow": r=int(FOG_R*1.4)
    elif CUR_TERRAIN=="desert": r=int(FOG_R*1.25)
    for i in range(32,0,-1):
        ri=int(r*i/32); a=max(0,min(242,int(242*(1-(i/32)**0.55))))
        pygame.draw.circle(_fog_surf,(*fog_col,a),(sx,sy),ri)
    screen.blit(_fog_surf,(0,0))

# ══════════════════════════════════════════════════════════════════════════════
#  HUD
# ══════════════════════════════════════════════════════════════════════════════
def draw_hud(player, fps, kills, total, elapsed, remote_players, net_latency_ms):
    # Bottom-left panel
    panel=pygame.Surface((280,145),pygame.SRCALPHA); panel.fill((5,12,5,180))
    screen.blit(panel,(10,H-155))
    hp_col=HUD_G if player.hp>50 else (HUD_Y if player.hp>25 else HUD_R)
    screen.blit(fnt_s.render(f"HP  {player.hp:>3}/{player.MAX_HP}",True,HUD_W),(18,H-150))
    pygame.draw.rect(screen,(40,40,40),(18,H-133,240,12))
    pygame.draw.rect(screen,hp_col,(18,H-133,int(240*player.hp/player.MAX_HP),12))
    pygame.draw.rect(screen,(80,80,80),(18,H-133,240,12),1)

    w=player.weapon
    ammo_col=HUD_G if player.ammo>w["max_ammo"]//3 else (HUD_Y if player.ammo>3 else HUD_R)
    astr="INF" if player.ammo==999 else f"{player.ammo:>3}/{w['max_ammo']}"
    screen.blit(fnt_s.render(f"{w['name']}  {astr}  [R]=reload",True,ammo_col),(18,H-115))

    slot_y=H-97
    for i,(wi,ammo) in enumerate(player.weapons):
        ww=WEAPONS[wi]; bc=ww["b_color"] if i==player.cur_weapon else (80,80,80)
        screen.blit(fnt_s.render(f"[{ww['slot']}]{ww['name'][:4]}",True,bc),(18+i*55,slot_y))

    spd=math.hypot(player.vx,player.vy)
    screen.blit(fnt_s.render(f"VEL {spd:>6.1f}px/s",True,(140,170,140)),(18,H-77))
    screen.blit(fnt_s.render(f"POS ({int(player.x):>5},{int(player.y):>5})",True,(140,170,140)),(18,H-62))

    # Network latency
    lat_col=HUD_G if net_latency_ms<30 else (HUD_Y if net_latency_ms<80 else HUD_R)
    screen.blit(fnt_s.render(f"PING {net_latency_ms:>4}ms",True,lat_col),(18,H-47))

    # Remote player latencies
    for i,(rid,rp) in enumerate(remote_players.items()):
        lc=HUD_G if rp.latency_ms<30 else (HUD_Y if rp.latency_ms<80 else HUD_R)
        screen.blit(fnt_s.render(f"{rid}: {rp.latency_ms}ms",True,lc),(18,H-30-i*14))

    # Kills top-left
    kpanel=pygame.Surface((200,32),pygame.SRCALPHA); kpanel.fill((5,12,5,180))
    screen.blit(kpanel,(10,10))
    screen.blit(fnt_m.render(f"KILLS  {kills} / {total}",True,HUD_G),(16,14))

    # FPS + time top-right
    fps_col=HUD_G if fps>=55 else (HUD_Y if fps>=30 else HUD_R)
    ppanel=pygame.Surface((180,52),pygame.SRCALPHA); ppanel.fill((5,12,5,180))
    screen.blit(ppanel,(W-190,10))
    screen.blit(fnt_m.render(f"FPS  {int(fps):>3}",True,fps_col),(W-184,14))
    screen.blit(fnt_s.render(f"TIME {int(elapsed):>4}s",True,(140,170,140)),(W-184,38))

    # Crosshair
    mx,my=pygame.mouse.get_pos(); sz=10
    pygame.draw.line(screen,ammo_col,(mx-sz,my),(mx+sz,my),1)
    pygame.draw.line(screen,ammo_col,(mx,my-sz),(mx,my+sz),1)
    pygame.draw.circle(screen,ammo_col,(mx,my),5,1)

    # Minimap
    mm_w,mm_h=140,int(140*ROWS/COLS); mm_x,mm_y=W-mm_w-10,68
    mm_surf=pygame.Surface((mm_w,mm_h),pygame.SRCALPHA); mm_surf.fill((10,15,10,160))
    sx_s=mm_w/COLS; sy_s=mm_h/ROWS
    for r in range(ROWS):
        for c in range(COLS):
            if MAP[r][c]==1:
                pygame.draw.rect(mm_surf,(60,60,55),(int(c*sx_s),int(r*sy_s),max(1,int(sx_s)),max(1,int(sy_s))))
    px_mm=int(player.x/MAP_W*mm_w); py_mm=int(player.y/MAP_H*mm_h)
    pygame.draw.circle(mm_surf,player.col,(px_mm,py_mm),3)
    for rp in remote_players.values():
        if rp.alive:
            rx_mm=int(rp.x/MAP_W*mm_w); ry_mm=int(rp.y/MAP_H*mm_h)
            pygame.draw.circle(mm_surf,rp.col,(rx_mm,ry_mm),3)
    pygame.draw.rect(mm_surf,(80,100,80),(0,0,mm_w,mm_h),1)
    screen.blit(mm_surf,(mm_x,mm_y))

# ══════════════════════════════════════════════════════════════════════════════
#  NETWORK CLIENT  (wraps UdpTransport, runs in background thread)
# ══════════════════════════════════════════════════════════════════════════════
class NetworkClient:
    def __init__(self, client_id, edge_addr, region, main_addr=None):
        self.client_id  = client_id
        self.edge_addr  = edge_addr   # (host, port)
        self.edge_name = "main" # changed after discover/selection
        self.region     = region
        self.main_addr = main_addr or edge_addr  # add this line after self.region = region
        self.transport  = UdpTransport(bind_port=0)
        self.server     = edge_addr
        self._seq       = 0
        self._seq_lock  = threading.Lock()
        self._running   = False
        
        self._discover_event = threading.Event()
        self._edges = []

        # Shared state written by recv thread, read by game thread
        self._lock               = threading.Lock()
        self.remote_states       = {}   # client_id → latest payload dict
        self.remote_latencies    = {}   # client_id → latency_ms
        self.remote_timestamps   = {}   # 
        self.pending_actions     = []   # list of action dicts to apply locally
        self.ping_ms             = 0

        # Register handlers
        self.transport.on(MessageType.PREDICTION.value, self._on_prediction)
        self.transport.on(MessageType.PONG.value,       self._on_pong)
        self.transport.on(MessageType.EDGE_LIST.value, self._on_edge_list)
        self._last_ping_seq = -1
        self._last_ping_t   = 0.0

    def _next_seq(self):
        with self._seq_lock:
            self._seq+=1; return self._seq

    def stop(self):
        self._running=False; self.transport.close()

    def connect(self):
        self._running = True
        self.transport.start()

        self._edges = []
        self._discover_event.clear()
        self._send_discover()

        if not self._discover_event.wait(timeout=20):
            raise RuntimeError("edge discovery failed")

        candidates = []
        for e in self._edges:

            candidates.append({
                "name": e.get("name", ""),
                "addr": (e["host"], int(e["port"])),
            })

        if not candidates:
            raise RuntimeError("no discovered edges")

        endpoints = [c["addr"] for c in candidates]

        best_result, results = choose_best_endpoint(
            self.transport,
            endpoints,
            self.client_id,
            self.region,
            n=7,
        )

        self.server = best_result.addr

        for c in candidates:
            if c["addr"] == self.server:
                self.edge_name = c["name"]
                break

        print(f"[net] selected endpoint {self.edge_name} @ {self.server}")

        self._send_register()

        t = threading.Thread(target=self._ping_loop, daemon=True)
        t.start()
        
    def _send_discover(self):
        seq = self._next_seq()

        msg = create_message(
            MessageType.DISCOVER.value,
            self.client_id,
            seq,
            payload={"region": self.region},
        )

        self.transport.send(msg, self.main_addr) # main addr, rename
    
    def _on_edge_list(self, msg, addr):
        self._edges = msg.get("payload", {}).get("edges", [])
        self._discover_event.set()
    
    def _send_register(self):
        seq = self._next_seq()

        reg = create_message(
            MessageType.REGISTER.value,
            self.client_id,
            seq,
            payload={
                "region": self.region,
                "registered_edge": self.edge_name,
                "registered_edge_addr": f"{self.server[0]}:{self.server[1]}",
            },
        )

        self.transport.send(reg, self.server)
        
    def send_state(self, player, tick, action=None):
        """Send PREDICTION with full player state + optional action."""
        seq=self._next_seq()
        payload={
            "tick": tick,
            "state": {
                "x":     player.x,
                "y":     player.y,
                "angle": player.angle,
                "hp":    player.hp,
            },
            "input": {"dx":0,"dy":0},   # kept for protocol compat
        }
        if action:
            payload["action"]=action
        msg=create_message(MessageType.PREDICTION.value,self.client_id,seq,payload=payload)
        self.transport.send(msg,self.server)

    def _on_prediction(self, msg, addr):
        source_id  = msg.get("client_id")
        send_ts    = msg.get("timestamp_ms", 0)
        now_ms     = int(_time.time()*1000)
        latency_ms = now_ms - send_ts
        payload    = msg.get("payload", {})

        if source_id is None or source_id == self.client_id:
            return

        with self._lock:
            self.remote_states[source_id]              = payload
            self.remote_latencies[source_id]           = latency_ms
            self.remote_timestamps[source_id]          = send_ts   # ← add this
            action = payload.get("action")
            if action:
                self.pending_actions.append({"source_id": source_id, "action": action, "latency_ms": latency_ms})

    def _on_pong(self, msg, addr):
        if msg.get("seq")==self._last_ping_seq:
            self.ping_ms=int((_time.time()-self._last_ping_t)*1000)

    def _ping_loop(self):
        while self._running:
            _time.sleep(1.0)
            seq=self._next_seq()
            self._last_ping_seq=seq
            self._last_ping_t=_time.time()
            msg = create_message(
                MessageType.PING.value,
                self.client_id,
                seq,
                payload={"region": self.region},
            )
            self.transport.send(msg,self.server)

    def drain_states(self):
        with self._lock:
            states     = dict(self.remote_states)
            lats       = dict(self.remote_latencies)
            timestamps = dict(self.remote_timestamps)   # ← add
            actions    = list(self.pending_actions)
            self.pending_actions.clear()
        return states, lats, timestamps, actions        # ← add

# ══════════════════════════════════════════════════════════════════════════════
#  SPAWN HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def spawn_enemies(n=20):
    enemies=[]
    attempts=0
    while len(enemies)<n and attempts<5000:
        attempts+=1
        c=random.randint(1,COLS-2); r=random.randint(1,ROWS-2)
        if MAP[r][c]==0:
            x=c*TILE+TILE//2; y=r*TILE+TILE//2
            if math.hypot(x-TILE*3,y-TILE*3)>TILE*8:
                enemies.append(Enemy(x,y))
    return enemies

def spawn_crates(n=12):
    crates=[]
    attempts=0
    while len(crates)<n and attempts<5000:
        attempts+=1
        c=random.randint(1,COLS-2); r=random.randint(1,ROWS-2)
        if MAP[r][c]==0:
            x=c*TILE+TILE//2; y=r*TILE+TILE//2
            if math.hypot(x-TILE*3,y-TILE*3)>TILE*5:
                wi=random.randint(1,len(WEAPONS)-1)
                crates.append(WeaponCrate(x,y,wi))
    return crates

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    global MAP, CUR_TERRAIN

    args=parse_args()

    # Parse edge address
    host,port=args.edge.split(":")
    edge_addr=(host,int(port))

    # Init map (same seed = same map for all players)
    CUR_TERRAIN=args.terrain
    MAP=gen_map(args.terrain, seed=args.map_seed)
    bake_map()

    # Spread player spawns across map so players don't stack
    random.seed(args.map_seed + hash(args.client_id))
    spawn_x = TILE * random.randint(2,6)
    spawn_y = TILE * random.randint(2,6)

    player=Player(args.color % len(PLAYER_COLORS))
    player.x=float(spawn_x); player.y=float(spawn_y)

    enemies=spawn_enemies(20 if args.ai else 0)
    crates=spawn_crates(12)
    bullets=[]
    remote_players={}   # client_id → RemotePlayer
    color_counter=[args.color+1]

    # Network
    main_addr = tuple(args.main.split(":")) if args.main else edge_addr
    main_addr = (main_addr[0], int(main_addr[1]))
    net=NetworkClient(args.client_id, edge_addr, region=args.region, main_addr=main_addr)
    print(f"[warzone] connecting to edge {edge_addr} as {args.client_id!r} ...")
    net.connect()
    print(f"[warzone] connected.")

    pygame.display.set_caption(f"WARZONE  — {args.client_id} @ {args.edge}")
    pygame.mouse.set_visible(False)

    tick=0
    elapsed=0.0
    kills=0
    total=len(enemies)
    game_over=False
    victory=False
    net_tick=0   # send every other frame

    scanlines=pygame.Surface((W,H),pygame.SRCALPHA)
    for y in range(0,H,3):
        pygame.draw.line(scanlines,(0,0,0,22),(0,y),(W,y))

    latency_log = []

    try:
        while True:
            dt=min(clock.tick(60)/1000.0, 0.05)
            fps=clock.get_fps()
            mx,my=pygame.mouse.get_pos()
            keys=pygame.key.get_pressed()

            # ── Events ──────────────────────────────────────────────────────────
            pending_shot=None
            for event in pygame.event.get():
                if event.type==pygame.QUIT:
                    net.stop(); pygame.quit(); return
                if event.type==pygame.KEYDOWN:
                    if event.key==pygame.K_ESCAPE:
                        net.stop(); pygame.quit(); return
                    if not game_over:
                        if event.key==pygame.K_r: player.reload()
                        if event.key==pygame.K_e:
                            for i,c in enumerate(crates):
                                if c.alive and math.hypot(c.x-player.x,c.y-player.y)<36:
                                    player.give_weapon(c.weapon_idx)
                                    c.alive=False
                                    net.send_state(player,tick,action={"type":"pickup","crate_idx":i})
                                    break
                        for num in range(pygame.K_1,pygame.K_8):
                            if event.key==num: player.switch_weapon(num-pygame.K_1+1)
                    if game_over and event.key==pygame.K_r:
                        net.stop(); latency_log.clear(); main(); return

            # ── Local game update ────────────────────────────────────────────────
            if not game_over:
                elapsed+=dt; tick+=1
                player.update(dt,keys,mx,my)

                # Shoot
                if pygame.mouse.get_pressed()[0]:
                    shots=player.shoot(bullets)
                    if shots: pending_shot=shots[0]

                # AI enemies
                for e in enemies:
                    if e.alive: e.update(dt,player,bullets)
                for c in crates:
                    if c.alive: c.update()
                for b in bullets:
                    b.update()

                # Bullet ↔ local player (from enemy/remote bullets)
                for b in bullets[:]:
                    if b.alive and b.owner_id not in ("local", args.client_id):
                        if math.hypot(b.x-player.x,b.y-player.y)<player.RADIUS+3:
                            player.take_hit(b.damage); b.alive=False
                            if not player.alive: game_over=True

                # Bullet ↔ enemies (local bullets only)
                for b in bullets[:]:
                    if b.alive and b.owner_id=="local":
                        for e in enemies:
                            if e.alive and math.hypot(b.x-e.x,b.y-e.y)<e.RADIUS+b.b_size:
                                e.take_hit(b.damage)
                                if b.special=="pierce":
                                    b.pierced+=1
                                    if b.pierced>=3: b.alive=False
                                elif b.special=="explode":
                                    b.alive=False; spawn_explosion(b.x,b.y)
                                    for e2 in enemies:
                                        if e2.alive and e2 is not e and math.hypot(b.x-e2.x,b.y-e2.y)<70:
                                            e2.take_hit(b.damage//2)
                                            if not e2.alive: kills+=1
                                elif b.special!="rail":
                                    b.alive=False
                                if not e.alive: kills+=1
                                if b.special not in ("pierce","rail"): break

                # Bullet ↔ remote players (local bullets → remote player hit)
                for b in bullets[:]:
                    if b.alive and b.owner_id=="local":
                        for rp in remote_players.values():
                            if rp.alive and math.hypot(b.x-rp.x,b.y-rp.y)<rp.RADIUS+b.b_size:
                                # Send hit notification — remote client applies damage
                                net.send_state(player,tick,action={
                                    "type":"hit","target_id":rp.client_id,"damage":b.damage})
                                spawn_blood(b.x,b.y,5)
                                if b.special not in ("pierce","rail"): b.alive=False
                                break

                bullets=[b for b in bullets if b.alive]

                if kills>=total and total>0: game_over=True; victory=True

                # ── Network: apply remote states ─────────────────────────────────
                states,lats,timestamps,actions=net.drain_states()

                # Update remote player objects
                for cid, payload in states.items():
                    if cid not in remote_players:
                        ci = color_counter[0] % len(PLAYER_COLORS)
                        color_counter[0] += 1
                        remote_players[cid] = RemotePlayer(cid, ci)
                    remote_players[cid].apply_state(payload, lats.get(cid, 0), timestamps.get(cid, 0))

                # Apply incoming actions
                for entry in actions:
                    src=entry["source_id"]; act=entry["action"]
                    atype=act.get("type")

                    if atype=="shoot":
                        # Spawn remote bullet locally
                        bx=float(act.get("bx",0)); by=float(act.get("by",0))
                        angle=float(act.get("angle",0))
                        widx=int(act.get("weapon_idx",0))
                        seed=int(act.get("spread_seed",0))
                        w=WEAPONS[widx]
                        rng=random.Random(seed)
                        for _ in range(w["count"]):
                            spread=rng.uniform(-w["spread"],w["spread"])
                            bullets.append(Bullet(bx,by,angle+spread,src,w,is_local=False))
                        spawn_flash(bx,by,angle)

                    elif atype=="hit" and act.get("target_id")==args.client_id:
                        # We were hit
                        player.take_hit(int(act.get("damage",0)))
                        if not player.alive: game_over=True

                    elif atype=="pickup":
                        idx=int(act.get("crate_idx",-1))
                        if 0<=idx<len(crates): crates[idx].alive=False

                # Send our state every 2nd frame (~30Hz)
                net_tick+=1
                if net_tick%2==0:
                    action=pending_shot  # may be None
                    if not player.alive and net_tick%60==0:
                        action={"type":"dead"}
                    net.send_state(player,tick,action=action)

                # Remove stale remote players (no update in 5s = disconnected)
                now=_time.time()
                for cid in list(remote_players.keys()):
                    if now-remote_players[cid].last_seen>5.0:
                        del remote_players[cid]

                update_particles()
                if player.alive:
                    update_cam(player.x,player.y)
                elif player.died_x is not None:
                    update_cam(player.died_x,player.died_y)

            # ── DRAW ────────────────────────────────────────────────────────────
            t=TERRAINS[CUR_TERRAIN]
            screen.fill(t["bg"])
            draw_map(screen,cam.x,cam.y)
            draw_particles(screen)

            for b in bullets: b.draw(screen)
            for c in crates:
                if c.alive: c.draw(screen)
            for e in enemies:
                if e.alive and math.hypot(e.x-player.x,e.y-player.y)<FOG_R+30:
                    e.draw(screen)

            # Draw remote players (always visible — no fog on other humans)
            for rp in remote_players.values():
                rp.draw(screen)

            if player.alive:
                player.draw(screen)
            elif player.died_x is not None:
                sx,sy=ws(player.died_x,player.died_y)
                if -20<sx<W+20 and -20<sy<H+20:
                    r=Player.RADIUS
                    pygame.draw.circle(screen,(80,20,20),(int(sx),int(sy)),r)
                    pygame.draw.line(screen,(160,40,40),(int(sx)-r+4,int(sy)-r+4),(int(sx)+r-4,int(sy)+r-4),3)
                    pygame.draw.line(screen,(160,40,40),(int(sx)+r-4,int(sy)-r+4),(int(sx)-r+4,int(sy)+r-4),3)
            if player.hurt_flash>0 and player.alive:
                t2=player.hurt_flash/0.18
                tint=pygame.Surface((W,H),pygame.SRCALPHA)
                tint.fill((180,0,0,int(60*t2))); screen.blit(tint,(0,0))

            draw_fog(player)
            screen.blit(scanlines,(0,0))
            draw_hud(player,fps,kills,total,elapsed,remote_players,net.ping_ms)

            # Crate pickup prompt
            if not game_over:
                for c in crates:
                    if c.alive and math.hypot(c.x-player.x,c.y-player.y)<50:
                        sx2,sy2=ws(c.x,c.y)
                        prompt=fnt_s.render("[E] PICK UP",True,CRATE_HL)
                        screen.blit(prompt,(int(sx2)-prompt.get_width()//2,int(sy2)+18))

            if game_over:
                overlay=pygame.Surface((W,H),pygame.SRCALPHA); overlay.fill((0,0,0,140))
                screen.blit(overlay,(0,0))
                msg="MISSION COMPLETE" if victory else "KIA"
                sub=f"TIME: {int(elapsed)}s   KILLS: {kills}/{total}" if victory else "KILLED IN ACTION"
                col=HUD_G if victory else HUD_R
                t1=fnt_xl.render(msg,True,col); t2=fnt_m.render(sub,True,HUD_W)
                t3=fnt_s.render("[R] RESTART  |  [ESC] QUIT",True,(120,140,120))
                screen.blit(t1,(W//2-t1.get_width()//2,H//2-70))
                screen.blit(t2,(W//2-t2.get_width()//2,H//2+10))
                screen.blit(t3,(W//2-t3.get_width()//2,H//2+52))

            pygame.display.flip()

            # Record latency data for this tick
            record = {"timestamp": _time.time(), "tick": tick}
            for cid, rp in remote_players.items():
                record[cid] = rp.latency_ms
            latency_log.append(record)

    finally:
        if latency_log:
            os.makedirs("logs", exist_ok=True)
            df = pd.DataFrame(latency_log)
            # Ensure timestamp and tick are the first columns
            cols = ["timestamp", "tick"] + [c for c in df.columns if c not in ["timestamp", "tick"]]
            df = df[cols]
            df.to_csv(f"logs/{args.client_id}.csv", index=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass