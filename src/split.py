#!/usr/bin/env python3
"""
Video Splitter for Instagram Auto Responder
- Skip first 1 minute of each video
- Create 80-second segments
- Maximum 10 parts per video
- Save to Instagram-Auto-Responder/split
- Delete original videos after splitting
"""

import os
import sys
import glob
import subprocess
from colorama import init, Fore, Style
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Initialize colorama
init()

def format_time(seconds):
    """Convert seconds to MM:SS format"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

def process_single_part(video_path, part_num, part_start, segment_duration, output_path, output_filename, total_parts):
    """Process a single video part - designed for parallel execution"""
    try:
        print(f"{Fore.YELLOW}⚡ Part {part_num}/{total_parts}: {format_time(part_start)} - {format_time(part_start + segment_duration)}{Style.RESET_ALL}")
        
        # FFmpeg command to extract segment (ULTRA FAST - no re-encoding)
        cmd = [
            'ffmpeg',
            '-ss', str(part_start),  # Seek before input for maximum speed
            '-i', video_path,
            '-t', str(segment_duration),
            '-c', 'copy',  # Stream copy - NO RE-ENCODING (10x faster)
            '-avoid_negative_ts', 'make_zero',
            '-y',  # Overwrite output files
            '-loglevel', 'error',  # Silent mode
            '-nostdin',  # No interaction
            output_path
        ]
        
        # Run FFmpeg command
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            print(f"{Fore.GREEN}🚀 Part {part_num} DONE: {output_filename} ({file_size:.1f} MB){Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}❌ Part {part_num} failed: {result.stderr[:50]}...{Style.RESET_ALL}")
            return False
            
    except Exception as e:
        print(f"{Fore.RED}❌ Part {part_num} error: {e}{Style.RESET_ALL}")
        return False

def get_video_duration(video_path):
    """Get video duration using ffprobe"""
    try:
        cmd = [
            'ffprobe', 
            '-v', 'quiet', 
            '-print_format', 'json', 
            '-show_format', 
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration = float(data['format']['duration'])
            return duration
        else:
            return None
    except Exception as e:
        print(f"{Fore.RED}❌ Error getting duration: {e}{Style.RESET_ALL}")
        return None

def split_video_ffmpeg(video_path, output_dir):
    """Split a single video using FFmpeg"""
    print(f"\n{Fore.CYAN}🎬 Processing: {os.path.basename(video_path)}{Style.RESET_ALL}")
    
    try:
        # Get video duration
        duration = get_video_duration(video_path)
        
        if duration is None:
            print(f"{Fore.RED}❌ Could not get video duration{Style.RESET_ALL}")
            return False
        
        print(f"{Fore.BLUE}📊 Video duration: {format_time(duration)}{Style.RESET_ALL}")
        
        # Skip first 1 minute (60 seconds)
        start_time = 60
        
        if duration <= start_time:
            print(f"{Fore.YELLOW}⚠️  Video too short (less than 1 minute), skipping...{Style.RESET_ALL}")
            return False
        
        # Calculate available duration after skipping first minute
        available_duration = duration - start_time
        print(f"{Fore.GREEN}✅ Available duration after skipping 1 min: {format_time(available_duration)}{Style.RESET_ALL}")
        
        # Video settings
        segment_duration = 80  # seconds
        max_parts = 10
        
        # Calculate how many parts we can create
        possible_parts = int(available_duration // segment_duration)
        actual_parts = min(possible_parts, max_parts)
        
        print(f"{Fore.BLUE}📈 Will create {actual_parts} parts of {segment_duration} seconds each{Style.RESET_ALL}")
        
        if actual_parts == 0:
            print(f"{Fore.YELLOW}⚠️  Not enough duration for even 1 segment, skipping...{Style.RESET_ALL}")
            return False
        
        # Get base filename without extension
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        
        # Create parts using parallel processing for MAXIMUM SPEED
        success_count = 0
        
        # Prepare all part tasks
        part_tasks = []
        for part_num in range(1, actual_parts + 1):
            part_start = start_time + (part_num - 1) * segment_duration
            output_filename = f"{base_name}_part{part_num:02d}.mp4"
            output_path = os.path.join(output_dir, output_filename)
            part_tasks.append((part_num, part_start, output_filename, output_path))
        
        print(f"{Fore.MAGENTA}🚀 Using parallel processing for ULTRA FAST splitting...{Style.RESET_ALL}")
        
        # Process parts in parallel (up to 4 concurrent processes)
        with ThreadPoolExecutor(max_workers=min(4, actual_parts)) as executor:
            # Submit all tasks
            future_to_part = {}
            for part_num, part_start, output_filename, output_path in part_tasks:
                future = executor.submit(process_single_part, video_path, part_num, part_start, segment_duration, output_path, output_filename, actual_parts)
                future_to_part[future] = part_num
            
            # Collect results as they complete
            for future in as_completed(future_to_part):
                part_num = future_to_part[future]
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                except Exception as e:
                    print(f"{Fore.RED}❌ Error in part {part_num}: {e}{Style.RESET_ALL}")
        # All parts processed in parallel above
        
        if success_count > 0:
            print(f"{Fore.GREEN}🎉 Successfully created {success_count} parts from {os.path.basename(video_path)}{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}💥 Failed to create any parts from {os.path.basename(video_path)}{Style.RESET_ALL}")
            return False
            
    except Exception as e:
        print(f"{Fore.RED}❌ Error processing {os.path.basename(video_path)}: {e}{Style.RESET_ALL}")
        return False

def get_video_files(downloads_dir):
    """Get all video files from downloads directory"""
    video_extensions = ['*.mp4', '*.avi', '*.mkv', '*.mov', '*.wmv', '*.flv', '*.webm']
    video_files = []
    
    for extension in video_extensions:
        pattern = os.path.join(downloads_dir, extension)
        video_files.extend(glob.glob(pattern))
    
    return video_files

def check_ffmpeg():
    """Check if FFmpeg is available"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            return True
        else:
            return False
    except FileNotFoundError:
        return False

def main():
    """Main function"""
    print(f"{Fore.MAGENTA}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}🎬 VIDEO SPLITTER FOR INSTAGRAM AUTO RESPONDER 🎬{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{'='*70}{Style.RESET_ALL}")
    
    # Check FFmpeg availability
    if not check_ffmpeg():
        print(f"{Fore.RED}❌ FFmpeg not found. Please install FFmpeg to use this script.{Style.RESET_ALL}")
        return
    
    print(f"{Fore.GREEN}✅ FFmpeg found and ready{Style.RESET_ALL}")
    
    # Define directories
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Instagram-Auto-Responder
    downloads_dir = os.path.join(base_dir, "downloads")
    split_dir = os.path.join(base_dir, "split")
    
    print(f"{Fore.CYAN}📁 Downloads directory: {downloads_dir}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}📁 Split directory: {split_dir}{Style.RESET_ALL}")
    
    # Check if downloads directory exists
    if not os.path.exists(downloads_dir):
        print(f"{Fore.RED}❌ Downloads directory not found: {downloads_dir}{Style.RESET_ALL}")
        return
    
    # Create split directory if it doesn't exist
    os.makedirs(split_dir, exist_ok=True)
    
    # Get all video files
    video_files = get_video_files(downloads_dir)
    
    if not video_files:
        print(f"{Fore.YELLOW}⚠️  No video files found in downloads directory{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.GREEN}📹 Found {len(video_files)} video files to process{Style.RESET_ALL}")
    
    # Process each video
    processed_count = 0
    deleted_count = 0
    
    for i, video_file in enumerate(video_files, 1):
        print(f"\n{Fore.BLUE}📊 Processing video {i}/{len(video_files)}{Style.RESET_ALL}")
        
        # Split the video
        success = split_video_ffmpeg(video_file, split_dir)
        
        if success:
            processed_count += 1
            
            # Delete original video after successful splitting
            try:
                os.remove(video_file)
                print(f"{Fore.GREEN}🗑️  Deleted original: {os.path.basename(video_file)}{Style.RESET_ALL}")
                deleted_count += 1
            except Exception as e:
                print(f"{Fore.RED}❌ Failed to delete {os.path.basename(video_file)}: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️  Keeping original file due to processing failure{Style.RESET_ALL}")
    
    # Summary
    print(f"\n{Fore.MAGENTA}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}📊 PROCESSING SUMMARY{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}✅ Videos processed successfully: {processed_count}/{len(video_files)}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}🗑️  Original videos deleted: {deleted_count}/{len(video_files)}{Style.RESET_ALL}")
    
    # Show split directory contents
    split_files = glob.glob(os.path.join(split_dir, "*.mp4"))
    print(f"{Fore.BLUE}📁 Total split files created: {len(split_files)}{Style.RESET_ALL}")
    
    if split_files:
        print(f"\n{Fore.CYAN}📋 Split files location: {split_dir}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}📋 Sample files:{Style.RESET_ALL}")
        for i, file in enumerate(split_files[:5]):  # Show first 5 files
            file_size = os.path.getsize(file) / (1024 * 1024)  # MB
            print(f"{Fore.YELLOW}   📄 {os.path.basename(file)} ({file_size:.1f} MB){Style.RESET_ALL}")
        if len(split_files) > 5:
            print(f"{Fore.YELLOW}   ... and {len(split_files) - 5} more files{Style.RESET_ALL}")
    
    print(f"\n{Fore.MAGENTA}🎉 Processing completed!{Style.RESET_ALL}")

if __name__ == "__main__":
    main()