import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def plot_single_file(file_path: str, ymax: float = None):
    """
    Plots all connection latencies over time for a single client CSV.
    """
    df = pd.read_csv(file_path)
    if 'timestamp' not in df.columns:
        print(f"Error: No timestamp column found in {file_path}")
        return
    
    # Normalize time to start at 0
    t0 = df['timestamp'].iloc[0]
    time_axis = df['timestamp'] - t0
    
    # Isolate just the target client ID columns
    plot_cols = [c for c in df.columns if c not in ['timestamp', 'tick']]
    
    plt.figure(figsize=(12, 6))
    for col in plot_cols:
        plt.plot(time_axis, df[col], label=f"To {col}")
        
    plt.xlabel("Time (seconds)")
    plt.ylabel("Latency (ms)")
    plt.title(f"Connection Latencies: {os.path.basename(file_path)}")
    plt.legend()
    plt.grid(True)
    if ymax is not None:
        plt.ylim(bottom=0, top=ymax)
    else:
        plt.ylim(bottom=0)
    plt.tight_layout()
    plt.show()

def align_dataframes(dfs: list[pd.DataFrame], framerate: float = 60.0):
    """
    Aligns multiple dataframes using numpy linear interpolation.
    Creates a common time index based on the earliest global timestamp 
    and samples exactly at the specified framerate.
    """
    if not dfs:
        return [], np.array([])

    # Find the global start and end times across all files
    min_t = min(df['timestamp'].min() for df in dfs)
    max_t = max(df['timestamp'].max() for df in dfs)
    
    # Create common time index exactly matching the framerate
    step = 1.0 / framerate
    common_time = np.arange(min_t, max_t + step, step)
    
    aligned_dfs = []
    for df in dfs:
        # Sort and remove duplicate timestamps
        clean_df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last')
        
        new_data = {}
        for col in clean_df.columns:
            if col == 'timestamp':
                continue
            valid_data = clean_df.dropna(subset=[col])
            if valid_data.empty:
                new_data[col] = np.full(len(common_time), np.nan)
            else:
                xp = valid_data['timestamp'].values
                yp = valid_data[col].values
                new_data[col] = np.interp(common_time, xp, yp, left=np.nan, right=np.nan)
                
        aligned_df = pd.DataFrame(new_data, index=common_time)
        aligned_df.index.name = 'timestamp'
        aligned_dfs.append(aligned_df)
        
    return aligned_dfs, common_time

# ─── User Defined Metric Extractors ──────────────────────────────────────────

def max_latency_nan(row: pd.Series):
    """Returns the max latency in a frame, ignoring missing (NaN) players."""
    return row.max(skipna=True)

def max_latency_strict(row: pd.Series):
    """Returns the max latency in a frame, returning NaN if ANY player is missing."""
    return row.max(skipna=False)

def mean_latency_nan(row: pd.Series):
    """Returns the mean latency of all players in a frame."""
    return row.mean(skipna=True)

def mean_latency_strict(row: pd.Series):
    """Returns the mean latency of all players in a frame."""
    return row.mean(skipna=False)

# ─────────────────────────────────────────────────────────────────────────────

def plot_metric_across_folder(folder_path: str, metric_func, framerate: float = 60.0, ymax: float = None):
    """
    Aligns all CSVs in a folder, extracts a metric for every frame, 
    and plots the mean of that metric across all clients.
    """
    csv_files = glob.glob(os.path.join(folder_path, "*.csv"))
    if not csv_files:
        print(f"No CSV files found in directory: {folder_path}")
        return
        
    dfs = [pd.read_csv(f) for f in csv_files]
    aligned_dfs, common_time = align_dataframes(dfs, framerate)
    
    # Calculate the per-frame metric for each individual client's file
    metric_series_list = []
    for df in aligned_dfs:
        lat_df = df.drop(columns=['tick'], errors='ignore')
        metric_series_list.append(lat_df.apply(metric_func, axis=1).to_numpy())
        
    # Combine all clients' metrics into one DF and take the mean across them
    combined_metrics = np.column_stack(metric_series_list)
    mean_of_metrics = combined_metrics.mean(axis=1)
    
    # Plotting
    time_axis = common_time - common_time[0]
    
    plt.figure(figsize=(12, 6))
    plt.plot(time_axis, mean_of_metrics, label=f"Average of {metric_func.__name__}", color='blue', linewidth=2)
    plt.xlabel("Time (seconds)")
    plt.ylabel("Latency Metric (ms)")
    plt.title(f"Average {metric_func.__name__} Across All Clients ({framerate} FPS)")
    # plt.legend()
    plt.grid(True)
    if ymax is not None:
        plt.ylim(bottom=0, top=ymax)
    elif not np.isnan(mean_of_metrics).all():
        plt.ylim(bottom=0, top=np.nanpercentile(mean_of_metrics, 90) * 1.1)
    else:
        plt.ylim(bottom=0)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    # Example 1: Plot a single client's raw data
    plot_single_file("logs/p1.csv")
    plot_single_file("logs/p2.csv")
    plot_single_file("logs/p3.csv")
    plot_single_file("logs/p4.csv")
    
    # Example 2: Plot the mean of everyone's max latency over the whole simulation
    plot_metric_across_folder("logs", max_latency_strict, framerate=60.0)
    ...