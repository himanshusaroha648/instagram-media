#!/usr/bin/env python3
"""
Replit 24/7 Runner for Instagram Auto-Responder
This script ensures your bot runs continuously on Replit
"""

import os
import sys
import time
import subprocess
from keep_alive import keep_alive

def main():
    """Main function to run the Instagram Auto-Responder continuously"""
    print("🚀 Starting Instagram Auto-Responder on Replit...")
    print("📡 Keep-alive server starting...")
    
    # Start the keep-alive server
    keep_alive()
    
    print("✅ Keep-alive server started on port 8080")
    print("🔄 Starting main application...")
    
    # Import and run the main application
    try:
        # Import the main module
        import main
        print("✅ Main module imported successfully")
        
        # Run the continuous workflow
        main.run_continuous_workflow()
        
    except KeyboardInterrupt:
        print("\n⏹️  Shutting down gracefully...")
        sys.exit(0)
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("🔄 Restarting in 30 seconds...")
        time.sleep(30)
        main()  # Restart
    except Exception as e:
        print(f"❌ Error: {e}")
        print("🔄 Restarting in 30 seconds...")
        time.sleep(30)
        main()  # Restart

if __name__ == '__main__':
    main()
