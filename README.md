# Apple Baseline Task Monitor

A Python script that monitors Apple's Baseline website for new research tasks/programs and alerts you when they become available.

## Features

- Automatically checks for new tasks every 10-20 seconds
- Works with multiple browsers (Chrome, Edge, Firefox)
- Provides both desktop notifications and voice alerts
- Automatically opens the Baseline website when a task is found
- Session management with cookie caching for persistent monitoring
- Detailed logging for troubleshooting
- Command-line interface with customizable options
- **Monitors both "Eligible Tasks" and "Training Tasks" sections** of the Apple Baseline page
- Detects changes in the task sections even when no specific task is identified
- Handles thank you/confirmation pages that appear when no tasks are available
- **Special support for tracking specific Training Tasks with counts**

## Requirements

- Python 3.6 or higher
- A modern web browser (Chrome, Edge, or Firefox) with an active login to Apple Baseline
- Windows for desktop notifications (win10toast)

## Installation

1. Clone this repository or download the files
2. Install the required dependencies:

```
pip install -r requirements.txt
```

## Usage

### Basic Version

1. Make sure you are logged into your Apple Baseline account in at least one browser
2. Run the script:

```
python baseline_monitor.py
```

3. Choose your preferred login method:
   - **Option 1: Clean Browser Session (Recommended)** - Opens a new browser window with a clean profile for you to log in
   - **Option 2: Existing Browser Cookies** - Uses cookies from your existing browsers
   - **Option 3: Manual Cookie Entry** - Allows you to manually extract and paste cookies

4. Follow the prompts to complete setup
5. Leave the script running in the background to monitor for new tasks

### Advanced Options

The script supports several command-line options:

```
python baseline_monitor.py [options]
```

Available options:

```
--debug               Enable debug mode with detailed logging
--interval MIN-MAX    Set custom check interval in seconds (e.g., 5-15)
--no-voice            Disable voice alerts
--quiet               Reduce console output
--only-eligible       Only check Eligible Tasks section (skip Training Tasks)
--display-expected    Display expected Training Tasks even if no changes detected
```

Examples:

```
# Run with 5-10 second intervals and debug logging
python baseline_monitor.py --interval 5-10 --debug

# Run silently (no voice alerts) 
python baseline_monitor.py --no-voice

# Run with minimal console output
python baseline_monitor.py --quiet

# Only monitor Eligible Tasks, not Training Tasks
python baseline_monitor.py --only-eligible

# Always display the expected Training Tasks in console
python baseline_monitor.py --display-expected
```

### Login Methods Explained

#### Clean Browser Session (Option 1)

This method is the most reliable as it:

- Opens a fresh browser instance with no existing cookies or cached data
- Creates a temporary user profile that is deleted after use
- Provides step-by-step instructions for extracting the necessary cookies
- Avoids issues with encrypted cookies in existing browsers

#### Existing Browser Cookies (Option 2)

This method attempts to extract cookies from:

- Chrome
- Edge
- Firefox

It may fail if your browser uses encryption that the script cannot access.

#### Manual Cookie Entry (Option 3)

If automatic methods fail, you can manually:

1. Open developer tools in your browser (F12)
2. Find cookies in the Network tab
3. Copy and paste them into the script

## Monitoring Training Tasks

The script now specifically monitors for the following Training Tasks:

- Search - Apple Music Top Hits
- Search - Apple Music Text Hints
- Search - Siri Music (End to End) v2 Training
- Search - Podcasts Top Hits Training
- Podcast - Tag Correctness
- Search - Music Text Hints (Side by Side)
- Search - Music Top Hits (Side by Side)
- Search - Podcasts Hints (suggestions) Training

When changes are detected in any of these tasks (including their counts), the script will:

1. Display a nicely formatted table in the console showing task names and counts
2. Provide notifications through the standard alert channels
3. Log the changes for review

You can use the `--display-expected` option to always show the expected tasks table, even when no changes are detected.

## Logging

The script creates a log file `baseline_monitor.log` that keeps track of all activities. This is useful for troubleshooting if you encounter any issues.

## Troubleshooting

- If you're not receiving alerts, make sure your browser cookies are accessible
- If you see "Unable to get key for cookie decryption" errors, try these solutions:
  1. Make sure Chrome/Edge is completely closed before running the script
  2. Use the manual cookie entry option when prompted
  3. Try using a different browser (Firefox, Edge, or Chrome)
- If the script fails to detect tasks, try logging into Baseline manually and restart the script
- Check the log file for detailed error messages
- Try running with `--debug` option to see more detailed logs

### Manual Cookie Entry

If the script cannot automatically extract cookies from your browsers, it will offer a manual cookie entry option:

1. Open Apple Baseline in your browser and log in
2. Press F12 to open Developer Tools
3. Go to the Network tab
4. Refresh the page
5. Click on any baseline.apple.com request
6. In the Headers tab, find the Cookie header
7. Copy the entire cookie value
8. Paste it when prompted by the script

## Notes

- The script relies on browser cookies to access your logged-in session
- No personal information is stored or transmitted outside your computer
- The automatic browser window opening functionality works best on Windows 

### Task Detection

The script monitors both the "Eligible Tasks" and "Training Tasks" sections of the Apple Baseline website, employing multiple detection methods:

1. **Section Change Detection**: Monitors changes to the task sections' HTML
2. **Task Keyword Detection**: Looks for keywords and specific task names
3. **Action Element Detection**: Finds buttons and links that might indicate available tasks
4. **Visual Indicator Detection**: Identifies "new" badges or highlight elements
5. **Table Structure Analysis**: Examines task tables to extract task names and counts

When any changes are detected, the script will:

- Play a voice alert
- Show a desktop notification
- Open the Apple Baseline website
- Log detailed information about the detected change
- Display a formatted table for Training Tasks 
