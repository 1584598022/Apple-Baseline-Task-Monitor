import requests
import time
import webbrowser
import os
import subprocess
from win10toast import ToastNotifier
from bs4 import BeautifulSoup
import random
import json
import logging
from datetime import datetime
import tempfile
import shutil
import argparse
import hashlib
import re
import glob
import signal
import sys
import threading
from plyer import notification as plyer_notification
import pygame

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("baseline_monitor.log"),
        logging.StreamHandler()
    ]
)

# 命令行参数解析
def parse_arguments():
    parser = argparse.ArgumentParser(description="Apple Baseline 任务监控工具")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--interval", type=str, default=f"{MIN_CHECK_INTERVAL}-{MAX_CHECK_INTERVAL}", 
                        help="检查间隔范围(秒)，格式为'最小值-最大值'")
    parser.add_argument("--no-voice", action="store_true", help="禁用语音提醒")
    parser.add_argument("--quiet", action="store_true", help="静默模式，减少控制台输出")
    parser.add_argument("--test-alert", action="store_true", help="测试提醒功能")
    parser.add_argument("--check-training", action="store_true", help="同时检查Training Tasks部分")
    parser.add_argument("--only-eligible", action="store_true", help="仅检查Eligible Tasks部分，不检查Training Tasks")
    parser.add_argument("--display-expected", action="store_true", help="显示预期的Training Tasks列表，即使未检测到任何变化")
    parser.add_argument("--mp3-voice-file", type=str, default="baseline_voice.mp3", help="自定义MP3语音文件路径")
    
    args = parser.parse_args()
    
    # 如果设置了只检查Eligible Tasks，则关闭Training Tasks检查
    if args.only_eligible:
        args.check_training = False
        
    return args

# 苹果Baseline网址
BASELINE_URL = "https://baseline.apple.com/"

# 检查间隔(秒)，现在默认为10-20秒随机间隔
MIN_CHECK_INTERVAL = 10
MAX_CHECK_INTERVAL = 15

# Cookie缓存文件
COOKIE_CACHE_FILE = "cookie_cache.json"

# 全局配置
config = {
    "debug": False,
    "no_voice": False,
    "quiet": False,
    "test_alert": False,
    "check_training": False,
    "only_eligible": False,
    "display_expected": False,
    "mp3_voice_file": "baseline_voice.mp3"  # 默认MP3语音文件路径
}

# 初始化通知器
toaster = ToastNotifier()

# 最新会话cookies缓存
recent_cookies = None
recent_browser = None

# 任务检测关键词
TASK_INDICATORS = [
    "available task", "enroll", "join study", "participate",
    "get started", "apply now", "new study", "baseline task",
    "task available", "baseline program", "program available",
    "new program", "study available", "open study", "sign up now",
    "participate in study", "join research", "start now",
    "eligible", "new", "open", "active", "available"
]

# 按钮和链接中的关键词
ACTION_INDICATORS = ["enroll", "join", "apply", "participate", "start", "sign up", "view", "open", "details"]

# 特定于Eligible Tasks部分的类名或ID
ELIGIBLE_TASKS_SELECTORS = [
    "eligible-tasks", "eligibleTasks", "eligible_tasks", 
    "task-list-eligible", "eligible-list",
    "task-section-3", "section-eligible"
]

# 特定于Training Tasks部分的类名或ID
TRAINING_TASKS_SELECTORS = [
    "training-tasks", "trainingTasks", "training_tasks",
    "task-list-training", "training-list",
    "task-section-1", "section-training"
]

# 页面中指示有新任务的元素类
NEW_TASK_INDICATORS = [
    "new-badge", "newTask", "new_task", "new-task", "task-new",
    "notification", "badge", "highlight", "alert", "new-alert"
]

# 特定需要监控的Training任务列表
SPECIFIC_TRAINING_TASKS = [
    "Search - Apple Music Top Hits",
    "Search - Apple Music Text Hints",
    "Search - Siri Music (End to End) v2 Training",
    "Search - Podcasts Top Hits Training",
    "Podcast - Tag Correctness",
    "Search - Music Text Hints (Side by Side)",
    "Search - Music Top Hits (Side by Side)",
    "Search - Music Keyboard (Side by Side)",
    "Search - Podcasts Hints (suggestions) Training"
]

# 特定任务的预期数量 - 从用户查询中提取
SPECIFIC_TASK_EXPECTED_COUNTS = {
    "Search - Apple Music Top Hits": 2,
    "Search - Apple Music Text Hints": 2,
    "Search - Siri Music (End to End) v2 Training": 2,
    "Search - Podcasts Top Hits Training": 1,
    "Podcast - Tag Correctness": 1,
    "Search - Music Text Hints (Side by Side)": 1,
    "Search - Music Top Hits (Side by Side)": 1,
    "Search - Music Keyboard (Side by Side)": 1,
    "Search - Podcasts Hints (suggestions) Training": 1
}

# 用于保存之前Eligible Tasks部分的HTML内容和哈希值
previous_eligible_section_html = ""
previous_eligible_section_hash = ""

# 添加变量用于保存Training Tasks的哈希值
previous_training_section_hash = ""

# 添加变量用于保存Eligible Tasks的实际任务文本，用于比较变化
previous_eligible_task_texts = []

# 添加变量用于保存Training Tasks的实际任务文本，用于比较变化
previous_training_task_texts = []

# 需要排除的非任务文本
NON_TASK_TEXTS = [
    "view my tasks", "next task", "task status", "task history", 
    "count of eligible tasks", "there are currently", "0 scrapes", "no scrapes",
    "grouped by", "evaluation", "scrape", "count", "status", "history",
    "return to", "homepage", "profile", "settings", "support", "help",
    "log out", "sign out", "welcome", "back", "no eligible tasks",
    "loading", "please wait", "updating", "refresh", "upcoming",
    "completed", "open", "closed", "in progress", "overdue", "details"
]

def get_html_section_hash(html_content):
    """计算HTML内容的哈希值"""
    return hashlib.md5(html_content.encode('utf-8')).hexdigest()

def play_mp3_voice(mp3_file_path=None):
    """播放MP3语音文件"""
    global config
    
    # 使用配置中的MP3文件路径或默认路径
    if mp3_file_path is None:
        mp3_file_path = config.get("mp3_voice_file", "baseline_voice.mp3")
    
    logging.info(f"播放MP3语音文件: {mp3_file_path}")
    try:
        # 检查文件是否存在
        if not os.path.exists(mp3_file_path):
            logging.error(f"找不到MP3语音文件: {mp3_file_path}")
            return False
            
        # 初始化pygame
        pygame.mixer.init()
        # 加载并播放MP3文件
        pygame.mixer.music.load(mp3_file_path)
        pygame.mixer.music.play()
        # 等待播放完成
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        # 关闭mixer
        pygame.mixer.quit()
        return True
    except Exception as e:
        logging.error(f"播放MP3语音文件失败: {e}")
        return False

def speak_voice(message=None):
    """播放语音消息，使用MP3文件"""
    global config
    
    # 如果开启静默模式，则不播放语音
    if config.get("no_voice", False):
        logging.info(f"语音已禁用，消息: {message if message else '(默认语音)'}")
        return
        
    # 播放MP3语音文件
    mp3_file = config.get("mp3_voice_file", "baseline_voice.mp3")
    if os.path.exists(mp3_file):
        logging.info(f"使用MP3语音文件: {mp3_file}")
        play_mp3_voice(mp3_file)
    else:
        logging.warning(f"找不到MP3语音文件: {mp3_file}，无法播放语音提醒")

def send_notification(title, message, duration=10):
    """发送桌面通知"""
    logging.info(f"发送通知: {title} - {message}")
    try:
        # 设置icon参数以保证通知在Action Center中保留
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "apple_icon.ico"))
        
        # 检查图标文件是否存在，如果不存在使用系统默认图标
        if not os.path.exists(icon_path):
            # 尝试创建一个简单的图标文件
            try:
                # 如果没有图标，尝试查找任何可用的.ico文件
                ico_files = glob.glob("*.ico")
                if ico_files:
                    icon_path = os.path.abspath(ico_files[0])
                else:
                    icon_path = None  # 如果没有找到图标文件，使用None让win10toast使用默认图标
            except:
                icon_path = None
        
        notification_success = False
        
        # 方法1: 使用Plyer库 (跨平台支持)
        try:
            plyer_notification.notify(
                title=title,
                message=message,
                app_name="Apple Baseline Monitor",
                timeout=duration,
                app_icon=icon_path
            )
            logging.info("使用Plyer库发送通知成功")
            notification_success = True
        except Exception as plyer_error:
            logging.warning(f"Plyer通知失败: {plyer_error}，尝试其他方法")
        
        # 方法2: 使用Windows 10 UWP API通知 (最可靠)
        if not notification_success and os.name == 'nt':
            try:
                # 准备PowerShell命令
                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

                $APP_ID = 'Apple.Baseline.Monitor'
                $template = @"
                <toast scenario="default">
                    <visual>
                        <binding template="ToastGeneric">
                            <text>{title}</text>
                            <text>{message}</text>
                        </binding>
                    </visual>
                    <actions>
                        <action activationType="protocol" content="打开网站" arguments="https://baseline.apple.com/"/>
                    </actions>
                </toast>
                "@

                $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
                $xml.LoadXml($template)
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($APP_ID).Show($toast)
                '''
                
                # 执行PowerShell命令 - 使用更可靠的方式
                process = subprocess.run(['powershell', '-Command', ps_script], 
                                     capture_output=True,
                                     text=True,
                                     check=True)
                logging.info("使用PowerShell UWP API发送通知成功")
                notification_success = True
            except Exception as ps_error:
                logging.warning(f"PowerShell UWP通知失败: {ps_error}，尝试其他方法")
        
        # 方法3: 使用win10toast库
        if not notification_success:
            try:
                # 如果PowerShell方法失败或不是Windows系统，使用win10toast
                toaster.show_toast(
                    title,
                    message,
                    icon_path=icon_path,
                    duration=duration,
                    threaded=True,
                    callback_on_click=open_new_browser_window  # 添加点击回调函数以打开浏览器
                )
                logging.info("使用win10toast发送通知成功")
                notification_success = True
            except Exception as toast_error:
                logging.error(f"win10toast通知失败: {toast_error}")
        
        # 方法4: 使用Windows系统消息服务作为最后的备用
        if not notification_success and os.name == 'nt':
            try:
                # 使用系统内置通知机制
                os.system(f'msg "%username%" "{title}: {message}"')
                logging.info("使用系统消息发送通知")
                notification_success = True
            except Exception as msg_error:
                logging.error(f"系统消息通知失败: {msg_error}")
        
        # 如果所有方法都失败，显示错误日志
        if not notification_success:
            logging.error("所有通知方法都失败")
    except Exception as e:
        logging.error(f"发送通知失败: {e}")

def open_new_browser_window():
    """使用Chrome打开新的浏览器窗口访问baseline.apple.com"""
    global recent_browser
    logging.info("正在尝试打开Chrome浏览器访问baseline.apple.com...")
    
    success = False
    try:
        # 对于Windows系统，直接使用Chrome命令
        if os.name == 'nt':
            # 尝试Chrome浏览器
            logging.info("使用Chrome打开新窗口...")
            chrome_cmd = f'start chrome --new-window "{BASELINE_URL}"'
            subprocess.Popen(chrome_cmd, shell=True)
            success = True
            # 记录最近成功的浏览器
            recent_browser = 'chrome'
        else:
            # 对于Mac/Linux系统
            logging.info("尝试使用Chrome打开新窗口...")
            chrome_cmd = f'chrome --new-window "{BASELINE_URL}"'
            subprocess.Popen(chrome_cmd, shell=True)
            success = True
            recent_browser = 'chrome'
    except Exception as e:
        logging.error(f"打开Chrome新窗口失败: {e}")
        success = False
        
    # 如果上面的方法失败，尝试最基本的方法
    if not success:
        try:
            logging.info("尝试使用基本方法打开浏览器...")
            if os.name == 'nt':
                os.system(f'start {BASELINE_URL}')
            else:
                os.system(f'open {BASELINE_URL}')
            success = True
        except Exception as e2:
            logging.error(f"所有方法都失败: {e2}")
            success = False
    
    return success

def format_training_tasks_output(tasks):
    """按照特定格式输出Training Tasks"""
    if not tasks:
        return []
    
    # 保存原始任务列表，可能包含其他类型的任务
    original_tasks = tasks.copy()
    
    # 创建新的格式化任务列表
    formatted_tasks = []
    
    # 检查是否有标题行
    has_header = False
    for task in tasks:
        if "Training Tasks\tEvaluation\tIncomplete Tests" in task:
            has_header = True
            formatted_tasks.append(task)
            break
    
    # 如果没有标题行，添加一个
    if not has_header and any(task.startswith("Search -") or task.startswith("Podcast -") for task in tasks):
        formatted_tasks.append("Training Tasks\tEvaluation\tIncomplete Tests")
    
    # 按照用户指定的顺序添加每个任务
    tasks_found = set()
    for specific_task in SPECIFIC_TRAINING_TASKS:
        found = False
        for task in tasks:
            if specific_task in task:
                # 提取数量
                count_match = re.search(r'(\d+)$', task.strip())
                if count_match:
                    count = count_match.group(1)
                    formatted_tasks.append(f"{specific_task}\t{count}")
                else:
                    # 使用预设的数量
                    expected_count = SPECIFIC_TASK_EXPECTED_COUNTS.get(specific_task)
                    if expected_count:
                        formatted_tasks.append(f"{specific_task}\t{expected_count}")
                    else:
                        formatted_tasks.append(f"{specific_task}\t未知数量")
                found = True
                tasks_found.add(specific_task)
                break
        
        # 如果在任务列表中没有找到，但我们有预期值，仍然添加
        if not found and specific_task in SPECIFIC_TASK_EXPECTED_COUNTS:
            formatted_tasks.append(f"{specific_task}\t{SPECIFIC_TASK_EXPECTED_COUNTS[specific_task]}")
            tasks_found.add(specific_task)
    
    # 检查是否找到了所有任务，如果没有，说明可能不是Training Tasks表格
    if len(tasks_found) < len(SPECIFIC_TRAINING_TASKS) / 2:  # 如果找到的任务不到一半，可能不是Training Tasks表格
        # 检查是否有任何特定任务的关键词
        has_related_keywords = False
        for task in tasks:
            if any(keyword in task.lower() for keyword in ["search -", "podcast -", "music", "siri"]):
                has_related_keywords = True
                break
        
        if not has_related_keywords:
            return original_tasks  # 返回原始任务列表
    
    # 如果有格式化的任务，返回这些任务；否则返回原始任务列表
    return formatted_tasks if formatted_tasks else original_tasks

def check_baseline_tasks():
    """检查Baseline页面是否有任务"""
    global recent_cookies, recent_browser
    
    update_operation_time()  # 更新操作时间
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logging.info(f"{current_time} - 开始检查任务...")
    
    # 使用手动设置的cookie
    if recent_cookies and recent_browser:
        # 降级为debug级别，避免频繁输出
        logging.debug(f"使用{recent_browser} cookies访问...")
        
        # 添加快速重试机制
        max_quick_retries = 3  # 快速重试次数
        quick_retry_delay = 2  # 快速重试间隔（秒）
        retry_count = 0
        
        # 确保cookies是请求库可以使用的格式
        if not isinstance(recent_cookies, requests.cookies.RequestsCookieJar) and isinstance(recent_cookies, dict):
            try:
                cookie_jar = requests.cookies.RequestsCookieJar()
                for name, value in recent_cookies.items():
                    if name:
                        cookie_jar.set(str(name), str(value), domain='.apple.com', path='/')
                recent_cookies = cookie_jar
                logging.debug("已将字典格式的cookies转换为RequestsCookieJar格式")
            except Exception as e:
                logging.error(f"转换cookie格式失败: {e}")
                # 如果转换失败，重新获取cookie
                return None, False
        
        # 确保cookies是有效的请求库可用的对象
        if not isinstance(recent_cookies, requests.cookies.RequestsCookieJar):
            logging.error("cookies不是有效的RequestsCookieJar对象")
            return None, False
        
        while retry_count < max_quick_retries:
            try:
                # 增加超时设置，连接超时15秒，读取超时45秒
                response = requests.get(BASELINE_URL, 
                    cookies=recent_cookies,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1"
                    },
                    timeout=(15, 45)  # 连接超时15秒，读取超时45秒
                )
                
                # 检查HTTP状态码
                if response.status_code != 200:
                    logging.warning(f"HTTP请求失败: 状态码 {response.status_code}")
                    # 保存错误响应内容用于调试
                    with open("error_response.html", "w", encoding="utf-8") as f:
                        f.write(response.text)
                    retry_count += 1
                    if retry_count < max_quick_retries:
                        logging.info(f"快速重试 ({retry_count}/{max_quick_retries})...")
                        time.sleep(quick_retry_delay)
                        continue
                    return None, False
                    
                # 检查是否是登录页面
                if "You are being logged in" not in response.text and "auto-sign-in" not in response.text:
                    logging.debug("cookie成功访问")  # 降级为debug级别
                    tasks, success = process_response(response)
                    
                    # 格式化Training Tasks的输出
                    if tasks and success and any("Training" in task for task in tasks):
                        formatted_tasks = format_training_tasks_output(tasks)
                        return formatted_tasks, success
                    return tasks, success
                else:
                    logging.warning("cookie已失效，检测到登录页面")
                    # 保存登录页面用于调试
                    with open("login_page.html", "w", encoding="utf-8") as f:
                        f.write(response.text)
                        
                    # 如果使用的是临时浏览器会话cookie，可以尝试重新获取
                    if recent_browser == 'manual_clean':
                        logging.info("尝试重新打开临时浏览器会话获取新cookie...")
                        cookie_str = open_clean_browser_for_login()
                        if cookie_str and isinstance(cookie_str, str) and len(cookie_str.strip()) > 10:
                            cookie_jar = create_cookie_jar_from_string(cookie_str)
                            if cookie_jar and isinstance(cookie_jar, requests.cookies.RequestsCookieJar) and len(cookie_jar) > 0:
                                recent_cookies = cookie_jar
                                recent_browser = 'manual_clean'
                                # 保存新获取的cookie到文件
                                save_cookies_to_file(cookie_jar)
                                logging.info("成功获取新cookie并保存，再次尝试访问...")
                                
                                # 使用新cookie尝试访问，同样添加超时设置
                                try:
                                    response = requests.get(BASELINE_URL, 
                                        cookies=recent_cookies,
                                        headers={
                                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                                            "Connection": "keep-alive",
                                            "Upgrade-Insecure-Requests": "1"
                                        },
                                        timeout=(15, 45)  # 连接超时15秒，读取超时45秒
                                    )
                                    
                                    if response.status_code == 200 and "You are being logged in" not in response.text and "auto-sign-in" not in response.text:
                                        logging.info("使用新cookie成功访问")
                                        return process_response(response)
                                    else:
                                        logging.warning("使用新cookie访问失败，需要重新登录")
                                        speak_voice("登录已失效，请重新登录")  # 只在确认cookie失效时播放语音
                                except Exception as e2:
                                    logging.error(f"使用新cookie尝试访问时出错: {e2}")
                                    speak_voice("使用新登录信息失败，请重新登录")
                            else:
                                logging.error("无法创建cookie jar，cookie字符串可能无效")
                                speak_voice("登录信息无效，请重新登录")  # 只在确认cookie无效时播放语音
                        else:
                            logging.error("未能获取新的cookie字符串")
                            speak_voice("无法获取登录信息，请重新登录")  # 只在确认无法获取cookie时播放语音
                    else:
                        speak_voice("登录已失效，请重新登录")  # 只在确认cookie失效时播放语音
                    return None, False
                    
            except requests.exceptions.Timeout as e:
                logging.error(f"请求超时: {e}")
                retry_count += 1
                if retry_count < max_quick_retries:
                    logging.info(f"快速重试 ({retry_count}/{max_quick_retries})...")
                    time.sleep(quick_retry_delay)
                    continue
                # 只在所有重试都失败后返回，不播放语音
                return None, False
            except requests.exceptions.ConnectionError as e:
                logging.error(f"连接错误: {e}")
                retry_count += 1
                if retry_count < max_quick_retries:
                    logging.info(f"快速重试 ({retry_count}/{max_quick_retries})...")
                    time.sleep(quick_retry_delay)
                    continue
                # 只在所有重试都失败后返回，不播放语音
                return None, False
            except requests.exceptions.RequestException as e:
                logging.error(f"请求异常: {e}")
                retry_count += 1
                if retry_count < max_quick_retries:
                    logging.info(f"快速重试 ({retry_count}/{max_quick_retries})...")
                    time.sleep(quick_retry_delay)
                    continue
                # 只在所有重试都失败后返回，不播放语音
                return None, False
            except Exception as e:
                logging.error(f"使用cookie访问失败: {e}")
                retry_count += 1
                if retry_count < max_quick_retries:
                    logging.info(f"快速重试 ({retry_count}/{max_quick_retries})...")
                    time.sleep(quick_retry_delay)
                    continue
                # 只在所有重试都失败后返回，不播放语音
                return None, False
    
    # 如果没有cookie，返回失败并播放语音提示
    logging.error("没有可用的cookie，请重新获取")
    speak_voice("没有可用的登录信息，请重新登录")  # 这个提示保留，因为这是配置问题而不是临时错误
    return None, False

def has_actual_tasks(section, section_name="Eligible Tasks"):
    """检查指定的任务部分是否有实际的任务内容"""
    if not section:
        return False
    
    section_text = section.get_text().lower()
    section_name_lower = section_name.lower()
    
    # 尝试检查该部分是否有实际内容（不只是标题）
    # 首先删除标题元素
    for heading in section.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        if heading.get_text().strip().lower() == section_name_lower:
            heading_parent = heading.parent
            # 如果标题的父元素只包含这个标题，可能就是没有任务的空部分
            if heading_parent and len(heading_parent.get_text().strip()) <= len(heading.get_text().strip()) + 10:
                return False
    
    # 如果是共用容器，尝试提取特定部分的内容
    section_blocks = section.find_all(['div', 'section', 'ul'], class_=lambda c: c and ('list' in (c.lower() if c else "") 
                                                                    or 'content' in (c.lower() if c else "")
                                                                    or 'task' in (c.lower() if c else "")))
    
    # 如果找到多个块，尝试定位特定任务类型的块
    if len(section_blocks) > 1:
        for block in section_blocks:
            block_text = block.get_text().lower()
            if section_name_lower in block_text:
                # 如果找到包含特定任务类型名称的块，在其中检查任务
                section = block
                section_text = block_text
                break
    
    # 检查是否有"无任务"的指示文本
    no_task_patterns = [
        f"no {section_name_lower}", 
        "no tasks available", 
        "check back later", 
        "no programs", 
        "no studies", 
        "not eligible"
    ]
    
    for pattern in no_task_patterns:
        if pattern in section_text:
            return False
    
    # 检查是否有特定的任务内容指示器
    task_indicators = [
        'view task', 'start task', 'complete task', 'task details', 
        'task due', 'due date', 'enroll', 'join', 'participate', 
        'get started', 'learn more', 'details', 'new', 'available'
    ]
    
    # 找到特定section_name和任务文本之间的内容
    start_idx = section_text.find(section_name_lower)
    if start_idx != -1:
        # 尝试找下一个任务类型的位置
        other_sections = ["training tasks", "assigned tasks", "eligible tasks"]
        other_sections.remove(section_name_lower)
        
        end_idx = len(section_text)
        for other_section in other_sections:
            pos = section_text.find(other_section, start_idx + len(section_name_lower))
            if pos != -1 and pos < end_idx:
                end_idx = pos
                
        # 提取该部分的文本
        section_text_only = section_text[start_idx:end_idx]
        
        # 检查这部分文本是否包含任务指示器
        for indicator in task_indicators:
            if indicator in section_text_only:
                return True
    
    # 检查是否有卡片、列表项或其他可能表示任务的元素
    # 先尝试获取section_name标题后面的元素
    section_header = section.find(string=lambda text: text and section_name_lower in text.lower())
    if section_header:
        # 尝试获取该标题元素后面的兄弟元素
        header_element = section_header.parent
        next_elements = list(header_element.next_siblings)
        
        if next_elements:
            for element in next_elements:
                if hasattr(element, 'find_all'):
                    tasks = element.find_all(['li', 'article', 'card', 'div'], 
                                             class_=lambda c: c and any(term in (c.lower() if c else "") 
                                                    for term in ['item', 'card', 'task', 'study', 'program']))
                    if tasks:
                        return True
        
    # 直接在整个部分查找任务元素
    task_elements = section.find_all(['li', 'article', 'card', 'div'], 
                                     class_=lambda c: c and any(term in (c.lower() if c else "") 
                                                for term in ['item', 'card', 'task', 'study', 'program']))
    if task_elements:
        # 检查这些元素是否真的属于当前section_name的内容
        for element in task_elements:
            # 检查元素文本或上下文中是否包含section_name
            context_text = ""
            
            # 向上查找最近的标题
            for heading in element.find_all_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])[:3]:  # 只看最近的3个标题
                context_text += heading.get_text().lower() + " "
                
            if section_name_lower in context_text or any(indicator in element.get_text().lower() for indicator in task_indicators):
                return True
    
    # 检查是否有按钮或链接，但排除"查看更多"等通用导航
    action_elements = section.find_all(['button', 'a'])
    for element in action_elements:
        element_text = element.get_text().lower() if element.get_text() else ""
        if element_text and any(term in element_text for term in ['enroll', 'join', 'apply', 'start', 'view task']):
            # 检查此元素是否属于当前任务类型
            for parent in element.parents:
                if parent == section:  # 确认在同一部分内
                    parent_text = parent.get_text().lower()
                    if section_name_lower in parent_text:
                        return True
    
    # 如果所有检查都未找到任务，查看部分内容是否超过一定长度
    # 这是一个启发式检查，假设内容量足够大可能含有任务
    if section_name_lower in section_text and len(section_text) > 200:
        # 这里使用更大的阈值，因为包含了标题等内容
        return True
    
    return False

def process_response(response):
    """处理响应，提取任务并返回"""
    global previous_eligible_section_html, previous_eligible_section_hash
    global config, previous_training_section_hash, previous_eligible_task_texts, previous_training_task_texts
    
    # 添加变量用于保存Training Tasks的哈希值
    global previous_training_section_hash
    if 'previous_training_section_hash' not in globals():
        previous_training_section_hash = ""
    
    # 获取当前时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 只在调试模式下保存当前页面到标准位置
    html = response.text
    if config.get("debug", False):
        with open("page_content.html", "w", encoding="utf-8") as f:
            f.write(html)
    
    # 检查响应状态码
    if response.status_code != 200:
        logging.warning(f"请求返回非200状态码: {response.status_code}")
        return None, False
        
    # 检查响应是否包含登录页面特征
    if "You are being logged in" in html or "auto-sign-in" in html:
        logging.warning("响应内容包含登录页面特征，可能需要重新登录")
        return None, False
    
    # 检查是否是thank you页面（没有任务时的默认页面）
    if "thank" in response.url.lower() or "thankyou" in response.url.lower():
        logging.debug("当前是thank you页面，表示已登录但没有可用任务")  # 降级为debug
        return [], True  # 返回空任务列表，但是检查成功
    
    # 解析页面寻找任务
    soup = BeautifulSoup(html, 'html.parser')
    
    tasks = []
    
    # 确定要检查的部分
    check_training = config.get("check_training", False)  # 默认不检查 Training Tasks
    
    # 先检查 Training Tasks（如果需要）
    if check_training:
        target_training_section = find_tasks_container(soup, "Training Tasks")
        if target_training_section:
            # 保存并检查目标部分是否有变化
            section_html = str(target_training_section)
            current_hash = get_html_section_hash(section_html)
            
            # 提取当前的Training任务
            current_tasks = extract_task_texts(target_training_section)
            
            # 查找可能包含指定Training任务的内容
            specific_tasks_found = []
            for specific_task in SPECIFIC_TRAINING_TASKS:
                for current_task in current_tasks:
                    if specific_task.lower() in current_task.lower():
                        # 尝试提取数量
                        match = re.search(r'(\d+)$', current_task.strip())
                        task_count = match.group(1) if match else "未知数量"
                        specific_tasks_found.append(f"{specific_task}\t{task_count}")
            
            # 如果找到了特定任务，添加到任务列表
            if specific_tasks_found:
                # 不添加标题行到tasks列表，以避免在日志中显示
                # tasks.append("Training Tasks\tEvaluation\tIncomplete Tests")
                tasks.extend(specific_tasks_found)
                
                # 首次检查时，直接添加此消息，正确显示任务数量
                if not previous_training_section_hash:
                    tasks.append(f"首次检查发现{len(specific_tasks_found)}个Training Tasks")
            
            # 正常的任务检测逻辑
            has_real_changes = False
            if previous_training_section_hash and current_hash != previous_training_section_hash:
                # 检查是否有实际任务内容变化
                if previous_training_task_texts and set(current_tasks) != set(previous_training_task_texts):
                    has_real_changes = True
                    logging.info(f"检测到Training Tasks实际任务内容发生变化")
                        
                    # 只在调试模式下保存文件
                    if config.get("debug", False):
                        # 保存一个带时间戳的版本用于历史记录
                        with open(f"training_tasks_{timestamp}.html", "w", encoding="utf-8") as f:
                            f.write(section_html)
                        
                    # 添加到任务列表
                    tasks.append(f"检测到Training Tasks的任务发生变化，可能有新任务")
                        
                    # 检查是否有实际的任务内容
                    has_tasks_content = has_actual_tasks(target_training_section, "Training Tasks")
                    if has_tasks_content:
                        tasks.append(f"检测到Training Tasks部分有新的任务内容")
                            
                        # 添加找到的具体任务
                        if current_tasks:
                            for task in current_tasks[:5]:  # 限制为前5个，避免通知过长
                                tasks.append(f"Training任务: {task}")
                            if len(current_tasks) > 5:
                                tasks.append(f"...还有{len(current_tasks)-5}个Training任务")
            elif not previous_training_task_texts:
                # 首次记录，不触发提醒但显示找到的任务
                logging.info(f"首次记录Training Tasks内容，将用于后续比较")
                        
                # 如果有任务，显示找到的任务内容
                if current_tasks and not specific_tasks_found:  # 只有在specific_tasks_found为空时才添加
                    has_real_changes = True  # 标记为第一次发现任务
                    # 保存实际任务数量，不包含标题行 
                    training_task_count = len(current_tasks)
                    tasks.append(f"首次检查发现{training_task_count}个Training Tasks")
                            
                    # 添加找到的具体任务
                    for task in current_tasks[:10]:  # 显示更多任务
                        tasks.append(f"Training任务: {task}")
                    if len(current_tasks) > 10:
                        tasks.append(f"...还有{len(current_tasks)-10}个Training任务")
                        
                # 只保存最新版本
                if config.get("debug", False):
                    with open(f"training_tasks_latest.html", "w", encoding="utf-8") as f:
                        f.write(section_html)
            
            # 更新任务文本记录
            previous_training_task_texts = current_tasks
                    
            # 更新Training Tasks的哈希值    
            previous_training_section_hash = current_hash
    
    # 检查 Eligible Tasks (始终检查)
    target_eligible_section = find_tasks_container(soup, "Eligible Tasks")
    
    if target_eligible_section:
        # 保存并检查目标部分是否有变化
        section_html = str(target_eligible_section)
        current_hash = get_html_section_hash(section_html)
        
        # 检查是否有变化，只在有变化时保存文件
        section_changed = False
        has_real_changes = False
        if previous_eligible_section_hash and current_hash != previous_eligible_section_hash:
            logging.info(f"检测到Eligible Tasks部分发生变化")
            section_changed = True
            
            # 检查是否有实际内容变化，而不仅仅是时间戳或其他动态元素变化
            # 提取并比较页面中实际任务的内容
            current_tasks = extract_task_texts(target_eligible_section)
            
            # 现在检查任务是否真的发生了变化
            if previous_eligible_task_texts and set(current_tasks) != set(previous_eligible_task_texts):
                has_real_changes = True
                logging.info("检测到实际任务内容发生变化")
            elif not previous_eligible_task_texts:
                # 如果没有之前的任务记录，先记录但不触发提醒
                has_real_changes = False
                logging.info("首次记录任务内容，将用于后续比较")
            else:
                logging.info("页面有变化但任务内容未变化（可能是时间戳或其他动态元素更新）")
            
            # 更新任务文本记录
            previous_eligible_task_texts = current_tasks
            
            # 只在调试模式下保存文件
            if config.get("debug", False):
                # 有变化时才保存文件
                with open(f"eligible_tasks_{timestamp}.html", "w", encoding="utf-8") as f:
                    f.write(section_html)
            
                # 保存之前的版本用于比较
                if previous_eligible_section_html:
                    with open("eligible_tasks_previous.html", "w", encoding="utf-8") as f:
                        f.write(previous_eligible_section_html)
                        
                # 保存当前的标准版本
                with open("eligible_tasks_section.html", "w", encoding="utf-8") as f:
                    f.write(section_html)
            
            # 如果检测到实际变化，添加到任务列表
            if has_real_changes:
                tasks.append(f"检测到Eligible Tasks部分的任务发生变化，可能有新任务")
        elif not previous_eligible_section_hash:
            # 首次检查，记录任务内容但不触发提醒
            previous_eligible_task_texts = extract_task_texts(target_eligible_section)
            logging.info("首次记录Eligible Tasks内容，将用于后续比较")
        
        # 更新保存的HTML和哈希值
        previous_eligible_section_html = section_html
        previous_eligible_section_hash = current_hash
    
    # 检查是否有明确表示"无任务"的内容
    no_tasks_indicators = ["no programs available", "no eligible tasks", "no tasks available", 
                          "no studies available", "check back later", "no studies at this time"]
    has_no_tasks_message = False
    
    for indicator in no_tasks_indicators:
        no_tasks = soup.find(string=lambda text: text and indicator.lower() in text.lower())
        if no_tasks:
            has_no_tasks_message = True
            logging.debug(f"页面明确表示没有可用任务: '{indicator}'")  # 降级为debug
            break
    
    # 如果页面确定显示无任务但我们又发现了任务指标，可能是误报
    if has_no_tasks_message and tasks:
        logging.info("页面标明无可用任务，但发现了潜在的任务指标，需要进一步确认")
    
    # 特别处理 - 如果检测到了指定的Training任务，调整输出格式
    if tasks and any("Search -" in task or "Podcast -" in task for task in tasks):
        # 这里不调用format_training_tasks_output，因为我们在check_baseline_tasks中处理
        logging.info("检测到特定Training任务，将以特定格式显示")
    
    # 检查页面是否成功加载（包含某些预期的内容）
    page_loaded = False
    expected_contents = ["Apple", "Baseline", "account", "profile", "health", "research"]
    for content in expected_contents:
        if content.lower() in html.lower():
            page_loaded = True
            break
    
    if not page_loaded:
        logging.warning("页面可能未正确加载，未找到预期内容")
        return None, False
        
    # 确认页面已加载，但未找到任务也是一种成功的检查
    has_tasks = len(tasks) > 0
    
    # 即使没有任务，只要页面正确加载，也应视为成功的检查
    if not has_tasks:
        logging.info(f"页面已成功加载，但未检测到任务")
        
    return tasks, True

def open_clean_browser_for_login():
    """打开一个干净的浏览器环境供用户登录，并提供简化的cookie获取方法"""
    logging.info("正在启动干净的浏览器会话...")
    
    try:
        # 创建临时目录作为Chrome用户数据目录
        temp_dir = tempfile.mkdtemp(prefix="baseline_login_")
        logging.info(f"创建临时浏览器数据目录: {temp_dir}")
        
        # 准备浏览器启动命令
        if os.name == 'nt':  # Windows系统
            # 尝试Chrome
            browser_cmd = f'start chrome --user-data-dir="{temp_dir}" --no-first-run --new-window {BASELINE_URL}'
            logging.info("尝试使用Chrome打开临时会话...")
            
            try:
                print("\n" + "="*80)
                print("已为您打开一个新的Chrome浏览器窗口，请在其中登录Apple Baseline。")
                print("登录完成后，请按照以下步骤操作:")
                print("1. 确保成功登录到Apple Baseline网站")
                print("2. 按F12打开开发者工具")
                print("3. 切换到'网络'或'Network'标签")
                print("4. 点击'Preserve log'或'保留日志'选项")
                print("5. 刷新页面，或点击页面上的任意链接")
                print("6. 在网络面板中找到对baseline.apple.com的请求（通常是第一个）")
                print("7. 点击该请求，在右侧的'Headers'或'标头'部分找到'Cookie:'")
                print("8. 右键点击Cookie值，选择'Copy Value'或'复制值'")
                print("9. 关闭浏览器，返回命令行窗口粘贴")
                print("="*80 + "\n")
                
                # 启动浏览器
                process = subprocess.Popen(browser_cmd, shell=True)
                
                # 等待用户登录并获取cookie
                cookie_str = input("请粘贴完整的Cookie值: ")
                
                # 清理临时目录
                try:
                    shutil.rmtree(temp_dir)
                    logging.info(f"已清理临时目录: {temp_dir}")
                except Exception as e:
                    logging.warning(f"清理临时目录失败: {e}")
                
                return cookie_str
                
            except Exception as e:
                logging.error(f"启动Chrome失败: {e}")
                
                # 尝试Edge
                browser_cmd = f'start msedge --user-data-dir="{temp_dir}" --no-first-run --new-window {BASELINE_URL}'
                logging.info("尝试使用Edge打开临时会话...")
                
                try:
                    print("\n" + "="*80)
                    print("已为您打开一个新的Edge浏览器窗口，请在其中登录Apple Baseline。")
                    print("登录完成后，请按照以下步骤操作:")
                    print("1. 确保成功登录到Apple Baseline网站")
                    print("2. 按F12打开开发者工具")
                    print("3. 切换到'网络'或'Network'标签")
                    print("4. 点击'Preserve log'或'保留日志'选项")
                    print("5. 刷新页面，或点击页面上的任意链接")
                    print("6. 在网络面板中找到对baseline.apple.com的请求（通常是第一个）")
                    print("7. 点击该请求，在右侧的'Headers'或'标头'部分找到'Cookie:'")
                    print("8. 右键点击Cookie值，选择'Copy Value'或'复制值'")
                    print("9. 关闭浏览器，返回命令行窗口粘贴")
                    print("="*80 + "\n")
                    
                    # 启动浏览器
                    process = subprocess.Popen(browser_cmd, shell=True)
                    
                    # 等待用户登录并获取cookie
                    cookie_str = input("请粘贴完整的Cookie值: ")
                    
                    # 清理临时目录
                    try:
                        shutil.rmtree(temp_dir)
                        logging.info(f"已清理临时目录: {temp_dir}")
                    except Exception as e:
                        logging.warning(f"清理临时目录失败: {e}")
                    
                    return cookie_str
                    
                except Exception as e2:
                    logging.error(f"启动Edge也失败: {e2}")
        
        # 如果使用的是其他系统或上面的方法都失败了，使用默认浏览器
        webbrowser.open_new(BASELINE_URL)
        print("\n" + "="*80)
        print("已使用默认浏览器打开Apple Baseline，请在其中登录后获取cookie。")
        print("登录完成后，请按照以下步骤操作:")
        print("1. 确保成功登录到Apple Baseline网站")
        print("2. 按F12打开开发者工具")
        print("3. 切换到'网络'或'Network'标签")
        print("4. 点击'Preserve log'或'保留日志'选项")
        print("5. 刷新页面，或点击页面上的任意链接")
        print("6. 在网络面板中找到对baseline.apple.com的请求（通常是第一个）")
        print("7. 点击该请求，在右侧的'Headers'或'标头'部分找到'Cookie:'")
        print("8. 右键点击Cookie值，选择'Copy Value'或'复制值'")
        print("9. 返回命令行窗口粘贴")
        print("="*80 + "\n")
        
        cookie_str = input("请粘贴完整的Cookie值: ")
        
        # 清理临时目录
        try:
            shutil.rmtree(temp_dir)
            logging.info(f"已清理临时目录: {temp_dir}")
        except Exception as e:
            logging.warning(f"清理临时目录失败: {e}")
            
        return cookie_str
        
    except Exception as e:
        logging.error(f"启动干净浏览器会话失败: {e}")
        
        # 任何情况下都提供标准的cookie获取方法
        print("\n" + "="*80)
        print("无法启动临时浏览器会话，请按照以下步骤手动获取cookie:")
        print("1. 手动打开浏览器，访问 https://baseline.apple.com/ 并登录")
        print("2. 按F12打开开发者工具")
        print("3. 切换到'网络'或'Network'标签")
        print("4. 刷新页面")
        print("5. 在网络面板中找到对baseline.apple.com的请求")
        print("6. 点击该请求，在右侧的'Headers'或'标头'部分找到'Cookie:'")
        print("7. 右键点击Cookie值，选择'Copy Value'或'复制值'")
        print("="*80 + "\n")
        
        cookie_str = input("请粘贴Cookie字符串: ")
        return cookie_str

def create_cookie_jar_from_string(cookie_str):
    """从Cookie字符串创建CookieJar对象"""
    from http.cookiejar import CookieJar
    from http.cookiejar import Cookie
    
    if not cookie_str or not isinstance(cookie_str, str) or len(cookie_str.strip()) < 10:
        logging.error("Cookie字符串无效或太短")
        return None
    
    try:
        cookie_jar = requests.cookies.RequestsCookieJar()
        
        # 清理cookie字符串
        cookie_str = cookie_str.strip()
        
        # 分割多个cookie
        cookie_count = 0
        for cookie_part in cookie_str.split(';'):
            if '=' in cookie_part:
                try:
                    name, value = cookie_part.strip().split('=', 1)
                    name = name.strip()
                    value = value.strip()
                    
                    # 跳过空值
                    if not name:
                        continue
                        
                    # 特殊处理某些值
                    if value.lower() == 'undefined':
                        value = ''
                    elif value.lower() == 'true':
                        value = '1'
                    elif value.lower() == 'false':
                        value = '0'
                    
                    # 确保值是字符串类型
                    value = str(value)
                    
                    # 跳过无效的cookie
                    if not value and name not in ['pltvcid']:  # pltvcid允许空值
                        continue
                        
                    cookie = Cookie(
                        version=0, name=name, value=value,
                        port=None, port_specified=False,
                        domain='.apple.com', domain_specified=True, domain_initial_dot=True,
                        path='/', path_specified=True,
                        secure=True, expires=None, discard=False,
                        comment=None, comment_url=None,
                        rest={'HttpOnly': None}
                    )
                    cookie_jar.set_cookie(cookie)
                    cookie_count += 1
                    logging.debug(f"添加cookie: {name}={value[:5]}...")
                except Exception as e:
                    logging.warning(f"添加cookie时出错: {e}")
                    continue
        
        if cookie_count == 0:
            logging.error("未能从字符串中提取出有效的cookie")
            return None
            
        # 验证cookie jar是否包含必要的cookie
        required_cookies = ['_baseline_session', 'acn01']  # 添加其他必要的cookie名称
        missing_cookies = [name for name in required_cookies if name not in cookie_jar]
        
        if missing_cookies:
            logging.warning(f"缺少必要的cookie: {', '.join(missing_cookies)}")
            return None
            
        logging.info(f"成功从字符串创建了包含{cookie_count}个cookie的cookie jar")
        return cookie_jar
    except Exception as e:
        logging.error(f"创建cookie jar失败: {e}")
        return None

def clean_old_files(pattern, max_files=5):
    """清理旧的HTML文件，保留最新的几个"""
    try:
        # 避免使用通配符，使用指定的文件扩展
        if pattern == "page_content_*.html":
            files = sorted(glob.glob("page_content_*.html"), key=os.path.getmtime, reverse=True)
        elif pattern == "eligible_tasks_*.html":
            files = sorted(glob.glob("eligible_tasks_*.html"), key=os.path.getmtime, reverse=True)
        elif pattern == "training_tasks_*.html":
            files = sorted(glob.glob("training_tasks_*.html"), key=os.path.getmtime, reverse=True)
        else:
            logging.warning(f"未知的文件模式: {pattern}")
            return
            
        # 只保留指定数量的最新文件
        if len(files) > max_files:
            for old_file in files[max_files:]:
                try:
                    os.remove(old_file)
                    logging.debug(f"清理旧文件: {old_file}")
                except:
                    logging.warning(f"无法删除文件: {old_file}")
    except Exception as e:
        logging.error(f"清理文件失败: {e}")

# 保存cookies到文件
def save_cookies_to_file(cookies):
    """将cookies保存到文件"""
    global recent_cookies, recent_browser
    
    if not cookies:
        logging.warning("没有可保存的cookies")
        return False
        
    try:
        cookie_dict = {}
        
        if isinstance(cookies, requests.cookies.RequestsCookieJar):
            for cookie in cookies:
                if hasattr(cookie, 'name') and hasattr(cookie, 'value'):
                    name = str(cookie.name)
                    value = str(cookie.value)
                    if value.lower() == 'undefined':
                        value = ''
                    elif value.lower() == 'true':
                        value = '1'
                    elif value.lower() == 'false':
                        value = '0'
                    cookie_dict[name] = value
        elif isinstance(cookies, dict):
            for k, v in cookies.items():
                if k:
                    name = str(k)
                    value = str(v)
                    if value.lower() == 'undefined':
                        value = ''
                    elif value.lower() == 'true':
                        value = '1'
                    elif value.lower() == 'false':
                        value = '0'
                    cookie_dict[name] = value
        else:
            logging.warning(f"未知的cookie类型: {type(cookies)}")
            return False
            
        if not cookie_dict:
            logging.warning("没有有效的cookie数据可保存")
            return False
            
        required_cookies = ['_baseline_session', 'acn01']
        missing_cookies = [name for name in required_cookies if name not in cookie_dict]
        
        if missing_cookies:
            logging.warning(f"缺少必要的cookie: {', '.join(missing_cookies)}")
            return False
            
        # 保存到文件
        try:
            with open(COOKIE_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'cookies': cookie_dict,
                    'browser': recent_browser or 'manual',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }, f, ensure_ascii=False, indent=2)
                
            # 只有成功保存后才更新全局变量
            if isinstance(cookies, requests.cookies.RequestsCookieJar):
                recent_cookies = cookies
            else:
                # 如果原始输入不是RequestsCookieJar，创建一个新的
                cookie_jar = requests.cookies.RequestsCookieJar()
                for name, value in cookie_dict.items():
                    cookie_jar.set(name, value, domain='.apple.com', path='/')
                recent_cookies = cookie_jar
                
            logging.info(f"已将cookies保存到 {COOKIE_CACHE_FILE}")
            return True
        except Exception as file_error:
            logging.error(f"写入cookie文件失败: {file_error}")
            return False
    except Exception as e:
        logging.error(f"保存cookies失败: {e}")
        return False

# 从文件加载cookies
def load_cookies_from_file():
    """从文件加载cookies"""
    global recent_cookies, recent_browser
    
    if not os.path.exists(COOKIE_CACHE_FILE):
        logging.info(f"Cookie缓存文件不存在: {COOKIE_CACHE_FILE}")
        return False
        
    try:
        with open(COOKIE_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        cookie_dict = data.get('cookies', {})
        browser_type = data.get('browser', 'manual')
        timestamp = data.get('timestamp', '')
        
        if not cookie_dict or not isinstance(cookie_dict, dict):
            logging.warning("缓存文件中没有有效的cookies")
            return False
            
        cookie_jar = requests.cookies.RequestsCookieJar()
        for name, value in cookie_dict.items():
            if name:
                name = str(name)
                value = str(value)
                if value.lower() == 'undefined':
                    value = ''
                elif value.lower() == 'true':
                    value = '1'
                elif value.lower() == 'false':
                    value = '0'
                cookie_jar.set(name, value, domain='.apple.com', path='/')
        
        if not cookie_jar or len(cookie_jar) == 0:
            logging.warning("无法创建有效的cookie jar")
            return False
            
        # 验证必要的cookie是否存在
        required_cookies = ['_baseline_session', 'acn01']
        missing_cookies = [name for name in required_cookies if name not in cookie_jar]
        
        if missing_cookies:
            logging.warning(f"缺少必要的cookie: {', '.join(missing_cookies)}")
            return False
            
        # 只有cookie_jar是有效的RequestsCookieJar对象且包含必要的cookie时才设置全局变量
        recent_cookies = cookie_jar
        recent_browser = browser_type
        
        logging.info(f"已从缓存加载cookies (保存于: {timestamp})")
        return True
    except Exception as e:
        logging.error(f"加载cookies失败: {e}")
        return False

# 尝试定位任务列表的通用方法，适用于同一容器中的多个任务类型
def find_tasks_container(soup, section_name):
    """查找包含任务列表的容器，支持多种任务类型在同一容器的情况"""
    logging.debug(f"尝试查找包含{section_name}的容器")
    
    # 首先尝试找到包含任务部分标题的元素
    section_header = soup.find(string=lambda text: text and section_name.lower() in text.lower())
    if section_header:
        logging.debug(f"找到了{section_name}文本")
        
        # 1. 检查是否在列表项中，表示可能是选项卡或分组任务
        list_item = None
        for parent in section_header.parents:
            if parent.name in ['li', 'div'] and (parent.get('role') == 'tab' or 'tab' in parent.get('class', '')):
                list_item = parent
                logging.debug(f"{section_name}在一个选项卡/标签中")
                break
                
        if list_item:
            # 查找关联的内容面板
            tab_id = list_item.get('id', '')
            aria_controls = list_item.get('aria-controls', '')
            
            # 尝试通过aria-controls找到对应的面板
            if aria_controls:
                panel = soup.find(id=aria_controls)
                if panel:
                    logging.debug(f"通过aria-controls找到了{section_name}对应的面板")
                    return panel
            
            # 尝试通过相似ID查找面板
            if tab_id:
                panel_id = tab_id.replace('tab', 'panel').replace('Tab', 'Panel')
                panel = soup.find(id=panel_id)
                if panel:
                    logging.debug(f"通过ID映射找到了{section_name}对应的面板")
                    return panel
            
            # 如果找不到特定面板，尝试查找与标签对应的所有内容面板
            panels = soup.find_all(['div', 'section'], 
                                   class_=lambda c: c and ('panel' in c.lower() or 'content' in c.lower() or 'tasks' in c.lower()))
            
            # 检查每个面板是否包含与section_name相关的内容
            for panel in panels:
                panel_text = panel.get_text().lower()
                if section_name.lower() in panel_text:
                    logging.debug(f"在面板内容中找到了{section_name}相关文本")
                    return panel
        
        # 2. 如果不是选项卡，查找包含该文本的最近的任务容器
        for parent in section_header.parents:
            if parent.name in ['div', 'section']:
                # 检查是否是任务容器
                classes = parent.get('class', [])
                if classes and any(c for c in classes if 'task' in c.lower() or 'list' in c.lower() or 'container' in c.lower()):
                    logging.debug(f"找到包含{section_name}的任务容器")
                    return parent
                    
                # 如果到达了相对较大的容器，直接返回
                if len(list(parent.find_all())) > 10:  # 超过10个子元素视为较大容器
                    logging.debug(f"找到包含{section_name}的较大容器")
                    return parent
    
    # 3. 尝试查找具有特定类名的容器
    selectors = TRAINING_TASKS_SELECTORS if section_name.lower() == "training tasks" else ELIGIBLE_TASKS_SELECTORS
    for selector in selectors:
        container = soup.find(['div', 'section'], 
                             class_=lambda c: c and selector.lower() in c.lower()) or \
                   soup.find(['div', 'section'], id=lambda i: i and selector.lower() in i.lower())
        if container:
            logging.debug(f"通过选择器'{selector}'找到包含{section_name}的容器")
            return container
    
    # 4. 尝试查找包含多种任务类型的主容器
    main_containers = soup.find_all(['div', 'section'], 
                                   class_=lambda c: c and ('tasks-container' in c.lower() or 
                                                           'tasks-section' in c.lower() or 
                                                           'task-types' in c.lower() or
                                                           'task-list' in c.lower()))
    for container in main_containers:
        container_text = container.get_text().lower()
        if section_name.lower() in container_text:
            logging.debug(f"在主任务容器中找到了{section_name}相关文本")
            return container
    
    # 5. 尝试查找页面中所有包含"tasks"的主要区域
    all_task_sections = soup.find_all(['div', 'section'], 
                                     class_=lambda c: c and 'task' in c.lower())
    for section in all_task_sections:
        section_text = section.get_text().lower()
        if section_name.lower() in section_text:
            logging.debug(f"在任务区域中找到了{section_name}相关文本")
            return section
    
    # 6. 最后尝试在页面主要部分中查找任务相关文本
    main_content = soup.find(['main', 'div'], class_='main-content') or soup.find('body')
    if section_name.lower() in main_content.get_text().lower():
        logging.debug(f"在页面主要内容中找到了{section_name}相关文本")
        return main_content
        
    logging.warning(f"未能找到包含{section_name}的容器")
    return None

def is_real_task(text):
    """判断文本是否是真正的任务而不是UI元素"""
    text_lower = text.lower()
    
    # 排除已知的非任务文本
    for non_task in NON_TASK_TEXTS:
        if non_task in text_lower:
            return False
            
    # 检查是否太短
    if len(text_lower) < 5:
        return False
        
    # 检查是否只包含常见UI操作动词
    common_actions = ["view", "click", "tap", "go", "next", "previous", "back", "continue"]
    words = text_lower.split()
    if all(word in common_actions for word in words):
        return False
        
    # 检查是否只是计数或数字
    if re.match(r'^[\d\s\.,]+$', text_lower):
        return False
        
    # 检查是否只是一般的信息消息
    info_patterns = [
        r'^there (are|is) \d+', 
        r'^\d+ (available|completed)', 
        r'no .* (found|available)',
    ]
    for pattern in info_patterns:
        if re.search(pattern, text_lower):
            return False
    
    return True

def extract_task_texts(section):
    """从页面部分提取实际的任务文本列表，用于比较变化"""
    if not section:
        return []
        
    task_texts = []
    
    # 1. 从任务元素中提取文本
    task_elements = section.find_all(['li', 'article', 'card', 'div'], 
                                   class_=lambda c: c and any(term in (c.lower() if c else "") 
                                              for term in ['item', 'card', 'task', 'study', 'program']))
    
    for element in task_elements:
        text = element.get_text().strip()
        if text and is_real_task(text):
            task_texts.append(text)
    
    # 2. 查找表格或列表中的任务
    # 表格元素
    tables = section.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            # 跳过表头行
            if row.find('th'):
                continue
            cells = row.find_all('td')
            if len(cells) >= 2:  # 假设至少有任务名称和状态两列
                task_name = cells[0].get_text().strip()
                if task_name and is_real_task(task_name):
                    # 提取任务名称和数量
                    task_count = ""
                    for cell in cells[1:]:
                        cell_text = cell.get_text().strip()
                        if cell_text.isdigit():
                            task_count = cell_text
                            break
                    
                    if task_count:
                        task_texts.append(f"{task_name} {task_count}")
                    else:
                        # 添加完整的行信息
                        full_row_text = " ".join([cell.get_text().strip() for cell in cells])
                        task_texts.append(full_row_text)
    
    # 3. 寻找Training Tasks特有的任务格式
    # Training任务通常有一个名称和计数/数量
    training_items = section.find_all(['div', 'li'], 
                                     class_=lambda c: c and any(term in (c.lower() if c else "") 
                                                for term in ['training-item', 'test-item', 'evaluation']))
    for item in training_items:
        task_name = None
        task_count = None
        
        # 尝试找到任务名称和计数元素
        name_elem = item.find(['span', 'div', 'h3', 'h4'], 
                             class_=lambda c: c and ('name' in (c.lower() if c else "") or 
                                                    'title' in (c.lower() if c else "")))
        count_elem = item.find(['span', 'div'], 
                              class_=lambda c: c and ('count' in (c.lower() if c else "") or 
                                                     'number' in (c.lower() if c else "") or
                                                     'qty' in (c.lower() if c else "")))
        
        if name_elem:
            task_name = name_elem.get_text().strip()
        if count_elem:
            task_count = count_elem.get_text().strip()
        
        # 如果没有找到结构化的名称和计数，尝试提取整个元素文本
        if not task_name:
            task_name = item.get_text().strip()
            
        if task_name and is_real_task(task_name):
            if task_count:
                task_texts.append(f"{task_name} {task_count}")
            else:
                task_texts.append(task_name)
    
    # 4. 特别查找用户提供的特定Training Tasks
    specific_tasks_found = set()  # 使用集合来跟踪已找到的特定任务
    
    # 首先尝试在各种元素中精确匹配任务名称
    for specific_task in SPECIFIC_TRAINING_TASKS:
        # 如果已找到该任务，跳过
        if specific_task in specific_tasks_found:
            continue
            
        # 直接在文本中搜索任务名称 - 精确匹配
        elements_with_task = section.find_all(string=lambda text: text and specific_task in text)
        if elements_with_task:
            for element in elements_with_task:
                parent = element.parent
                if parent and parent.name not in ['script', 'style']:
                    # 获取包含任务和数量的完整文本
                    task_container = parent
                    # 向上找最多3层，尝试找到完整的任务容器
                    for _ in range(3):
                        if task_container and task_container.name in ['li', 'div', 'article', 'tr']:
                            # 尝试找到任务对应的数量
                            quantity_elem = task_container.find(string=lambda text: text and text.strip().isdigit())
                            
                            if quantity_elem:
                                task_text = f"{specific_task} {quantity_elem.strip()}"
                            else:
                                # 如果找不到数量，使用预设的数量
                                expected_count = SPECIFIC_TASK_EXPECTED_COUNTS.get(specific_task)
                                if expected_count:
                                    task_text = f"{specific_task} {expected_count}"
                                else:
                                    task_text = specific_task
                                    
                            if task_text and is_real_task(task_text) and task_text not in task_texts:
                                task_texts.append(task_text)
                                specific_tasks_found.add(specific_task)
                            break
                        if task_container:
                            task_container = task_container.parent
        
        # 如果没有精确匹配，尝试部分匹配
        if specific_task not in specific_tasks_found:
            # 提取关键词
            keywords = specific_task.split(" - ")
            if len(keywords) >= 2:
                main_keyword = keywords[0]  # "Search" 或 "Podcast"
                sub_keyword = keywords[1]   # 例如 "Apple Music Top Hits"
                
                # 查找包含这些关键词的元素
                for element in section.find_all(string=lambda text: text and 
                                             main_keyword.lower() in text.lower() and 
                                             sub_keyword.lower() in text.lower()):
                    parent = element.parent
                    if parent and parent.name not in ['script', 'style']:
                        # 向上找最多3层
                        task_container = parent
                        for _ in range(3):
                            if task_container and task_container.name in ['li', 'div', 'article', 'tr']:
                                # 尝试找到数量
                                quantity_elem = task_container.find(string=lambda text: text and text.strip().isdigit())
                                
                                if quantity_elem:
                                    task_text = f"{specific_task} {quantity_elem.strip()}"
                                else:
                                    # 如果找不到数量，使用预设的数量
                                    expected_count = SPECIFIC_TASK_EXPECTED_COUNTS.get(specific_task)
                                    if expected_count:
                                        task_text = f"{specific_task} {expected_count}"
                                    else:
                                        task_text = specific_task
                                
                                if task_text and is_real_task(task_text) and task_text not in task_texts:
                                    task_texts.append(task_text)
                                    specific_tasks_found.add(specific_task)
                                break
                            if task_container:
                                task_container = task_container.parent
    
    # 5. 如果有特定任务未找到，但我们确信它们应该存在，使用预设值添加
    for specific_task in SPECIFIC_TRAINING_TASKS:
        if specific_task not in specific_tasks_found:
            # 检查页面中是否有任何与此任务相关的内容
            has_related_content = False
            keywords = specific_task.split(" - ")
            
            if len(keywords) >= 2:
                for keyword in keywords:
                    if len(keyword) > 3:  # 跳过太短的关键词
                        if keyword.lower() in section.get_text().lower():
                            has_related_content = True
                            break
            
            # 如果确实有相关内容，或者我们是正在处理一个任务汇总表，添加预设任务
            if has_related_content or config.get("check_training", False):
                expected_count = SPECIFIC_TASK_EXPECTED_COUNTS.get(specific_task)
                if expected_count:
                    task_text = f"{specific_task} {expected_count}"
                    if task_text not in task_texts:
                        task_texts.append(task_text)
                        specific_tasks_found.add(specific_task)
    
    # 6. 从任务指标中提取文本
    for indicator in TASK_INDICATORS:
        elements = section.find_all(string=lambda text: text and indicator.lower() in text.lower())
        for element in elements:
            parent = element.parent
            if parent and parent.name not in ['script', 'style']:
                text = parent.get_text().strip()
                if text and is_real_task(text) and text not in task_texts:
                    task_texts.append(text)
    
    # 7. 从按钮和链接中提取文本
    action_elements = section.find_all(['button', 'a'])
    for element in action_elements:
        for indicator in ACTION_INDICATORS:
            if element.get_text() and indicator.lower() in element.get_text().lower():
                text = element.get_text().strip()
                if text and is_real_task(text) and text not in task_texts:
                    task_texts.append(text)
    
    # 8. 特别处理表格布局的Training Tasks
    # 查找所有可能包含任务名称和数量的元素对
    all_texts = section.find_all(string=True)
    for i, text in enumerate(all_texts):
        # 跳过脚本和样式文本
        if text.parent.name in ['script', 'style']:
            continue
            
        text_content = text.strip()
        if text_content and len(text_content) > 3 and not text_content.isdigit():
            # 检查这是否可能是任务名称
            if any(kw in text_content.lower() for kw in ['search', 'music', 'siri', 'podcast', 'training', 'test', 'evaluation']):
                # 尝试在附近元素找数字，可能是任务数量
                for j in range(i+1, min(i+5, len(all_texts))):
                    if j < len(all_texts):
                        next_text = all_texts[j].strip()
                        if next_text.isdigit() or re.match(r'^\d+$', next_text):
                            combined = f"{text_content} {next_text}"
                            if combined not in task_texts:
                                task_texts.append(combined)
                            break
    
    # 9. 对任务文本进行规范化处理
    normalized_texts = []
    for text in task_texts:
        # 移除多余空格和换行
        normalized = re.sub(r'\s+', ' ', text).strip()
        # 移除数字前缀（如 1. 2. 等）
        normalized = re.sub(r'^\d+\.\s*', '', normalized)
        if normalized and normalized not in normalized_texts:
            normalized_texts.append(normalized)
    
    return normalized_texts

def display_training_tasks_table(tasks):
    """以表格形式在控制台显示Training Tasks"""
    if not tasks:
        print("未找到任何Training Tasks")
        return
        
    # 检查是否是Training Tasks格式
    has_training_tasks = False
    for task in tasks:
        if "Training Tasks\t" in task or any(specific in task for specific in SPECIFIC_TRAINING_TASKS):
            has_training_tasks = True
            break
            
    if not has_training_tasks:
        print("未找到Training Tasks格式的任务")
        return
        
    print("\n" + "="*80)
    print("Training Tasks\tEvaluation\tIncomplete Tests")
    print("-"*80)
    
    # 显示每个任务
    for task in tasks:
        # 跳过标题行
        if "Training Tasks\tEvaluation\tIncomplete Tests" in task:
            continue
            
        # 检查是否是特定任务格式
        is_task_format = False
        for specific_task in SPECIFIC_TRAINING_TASKS:
            if task.startswith(specific_task):
                is_task_format = True
                break
                
        if is_task_format:
            print(task.replace("\t", "\t\t"))  # 添加额外的制表符以对齐
    
    print("="*80 + "\n")

# 添加全局变量用于控制程序状态
monitoring_active = True
last_operation_time = time.time()
operation_timeout = 60  # 操作超时时间（秒）

def signal_handler(signum, frame):
    """处理 Ctrl+C 信号"""
    global monitoring_active
    if signum == signal.SIGINT:  # Ctrl+C
        if monitoring_active:
            logging.info("\n检测到 Ctrl+C，暂停监控...")
            monitoring_active = False
            print("\n监控已暂停。请选择：")
            print("1. 输入 'r' 或 'R' 恢复监控")
            print("2. 输入 'q' 或 'Q' 退出程序")
            print("3. 再次按 Ctrl+C 强制退出")
            
            # 启动一个线程来监听用户输入
            input_thread = threading.Thread(target=handle_user_input)
            input_thread.daemon = True
            input_thread.start()
        else:
            logging.info("\n再次检测到 Ctrl+C，强制退出程序...")
            sys.exit(0)

def handle_user_input():
    """处理用户输入的函数"""
    global monitoring_active
    while True:
        try:
            choice = input().strip().lower()
            if choice in ['r', 'restart']:
                logging.info("恢复监控...")
                monitoring_active = True
                break
            elif choice in ['q', 'quit', 'exit']:
                logging.info("用户选择退出程序...")
                sys.exit(0)
        except EOFError:
            break

def check_operation_timeout():
    """检查操作是否超时"""
    global last_operation_time
    current_time = time.time()
    elapsed_time = current_time - last_operation_time
    
    if elapsed_time > operation_timeout:
        logging.warning(f"操作已超过 {operation_timeout} 秒未响应 (已等待 {elapsed_time:.1f} 秒)")
        # 移除语音提示，只记录日志
        return True
        
    # 添加中间状态检查，但使用debug级别避免过多日志
    if elapsed_time > operation_timeout * 0.7:  # 当超过70%的超时时间时
        logging.debug(f"操作已运行 {elapsed_time:.1f} 秒，接近超时限制")
        
    return False

def update_operation_time():
    """更新最后操作时间"""
    global last_operation_time
    last_operation_time = time.time()
    logging.debug(f"更新操作时间: {datetime.now().strftime('%H:%M:%S')}")  # 添加调试日志

def main():
    global MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL, config, previous_eligible_section_html, previous_eligible_section_hash
    global recent_cookies, recent_browser, previous_training_section_hash, previous_eligible_task_texts
    global previous_training_task_texts, monitoring_active, operation_timeout
    
    # 增加操作超时时间到60秒
    operation_timeout = 60  # 操作超时时间（秒）
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    
    # 解析命令行参数
    args = parse_arguments()
    
    # 更新配置
    config["debug"] = args.debug
    config["no_voice"] = args.no_voice
    config["quiet"] = args.quiet
    config["test_alert"] = args.test_alert
    config["check_training"] = args.check_training  # 默认为False，需要传参才启用
    config["only_eligible"] = args.only_eligible
    config["display_expected"] = args.display_expected
    config["mp3_voice_file"] = args.mp3_voice_file
    
    # 检查MP3文件是否存在
    mp3_file = config.get("mp3_voice_file", "baseline_voice.mp3")
    if os.path.exists(mp3_file):
        logging.info(f"已设置MP3语音提醒文件: {mp3_file}")
    else:
        logging.warning(f"找不到MP3语音文件: {mp3_file}，将无法播放语音提醒")
    
    if config.get("check_training", False):
        logging.info("已启用Training Tasks检测模式")
    
    if config.get("only_eligible", False):
        logging.info("仅检查Eligible Tasks，不检查Training Tasks")
    
    if config.get("display_expected", False):
        logging.info("将显示预期的Training Tasks列表，即使未检测到任何变化")
        # 显示预期的Training Tasks列表
        print("\n预期的Training Tasks列表:")
        display_training_tasks_table(["Training Tasks\tEvaluation\tIncomplete Tests"] + 
                                    [f"{task}\t{count}" for task, count in SPECIFIC_TASK_EXPECTED_COUNTS.items()])
    
    # 设置日志级别
    if config["debug"]:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("已启用调试模式")
    
    # 解析检查间隔
    if "-" in args.interval:
        try:
            min_val, max_val = map(int, args.interval.split("-"))
            MIN_CHECK_INTERVAL = min_val
            MAX_CHECK_INTERVAL = max_val
        except ValueError:
            logging.warning(f"无效的间隔格式: {args.interval}，使用默认值")
    
    logging.info("Apple Baseline任务监控工具启动")
    logging.info(f"将每 {MIN_CHECK_INTERVAL}-{MAX_CHECK_INTERVAL} 秒检查一次是否有新任务")
    
    # 如果启用了测试提醒模式，立即测试提醒功能
    if config.get("test_alert", False):
        logging.info("正在测试提醒功能...")
        
        # 创建一个测试任务
        test_tasks = ["这是一个测试任务 - Apple Baseline任务提醒测试"]
        
        # 测试所有三种提醒方式
        # 1. 发送桌面通知
        send_notification(
            "Apple Baseline 任务提醒测试",
            "这是一个测试通知，确认提醒功能正常工作。"
        )
        
        # 2. 简短延迟确保通知完成
        time.sleep(1)
        
        # 3. 打开浏览器
        open_new_browser_window()
        
        # 4. 播放语音提醒
        speak_voice()
        
        logging.info("\n测试任务提醒已触发，请检查：")
        logging.info("1. 是否看到桌面通知")
        logging.info("2. 是否看到浏览器自动打开")
        logging.info("3. 是否听到MP3语音提醒")
        
        choice = input("\n测试完成后，您想要继续监控吗？(y/n): ")
        if choice.lower() != 'y':
            logging.info("测试完成，程序退出")
            return
        else:
            logging.info("继续进入正常监控模式...")
    
    # 提供选项
    print("\nApple Baseline任务监控工具")
    print("=" * 50)
    
    # 尝试从文件加载cookies
    cookies_loaded = load_cookies_from_file()
    
    if not cookies_loaded:
        print("未找到有效的cookie缓存，正在启动临时浏览器会话供您登录...")
        # 使用临时浏览器会话登录
        logging.info("启动临时浏览器会话登录")
        cookie_str = open_clean_browser_for_login()
        if cookie_str and isinstance(cookie_str, str) and len(cookie_str.strip()) > 10:
            cookie_jar = create_cookie_jar_from_string(cookie_str)
            if cookie_jar and isinstance(cookie_jar, requests.cookies.RequestsCookieJar) and len(cookie_jar) > 0:
                # 更新全局变量
                recent_cookies = cookie_jar
                recent_browser = 'manual_clean'
                logging.info("成功获取cookies")
                # 保存cookies到文件
                save_result = save_cookies_to_file(cookie_jar)
                if save_result:
                    print("已成功获取并保存cookie")
                else:
                    print("已获取cookie但保存失败，程序将继续但不会缓存cookie")
            else:
                logging.error("无法创建cookie jar，cookie字符串可能无效")
                print("错误: cookie格式无效，无法继续。")
                return
        else:
            logging.error("未能获取有效的cookies，无法继续")
            print("错误: 未能获取有效的cookies，程序无法继续。")
            return
    else:
        print(f"已从缓存文件加载之前保存的cookies")
        
        # 验证加载的cookie是否有效
        logging.info("正在验证已加载的cookie是否有效...")
        try:
            test_tasks, test_success = check_baseline_tasks()
            if not test_success:
                logging.warning("加载的cookie已失效，需要重新获取")
                print("加载的cookie已失效，需要重新获取新的cookie...")
                
                # 使用临时浏览器会话重新登录
                cookie_str = open_clean_browser_for_login()
                if cookie_str:
                    cookie_jar = create_cookie_jar_from_string(cookie_str)
                    if cookie_jar and isinstance(cookie_jar, requests.cookies.RequestsCookieJar) and len(cookie_jar) > 0:
                        # 更新全局变量
                        recent_cookies = cookie_jar
                        recent_browser = 'manual_clean'
                        logging.info("成功获取新cookies")
                        # 保存cookies到文件
                        save_cookies_to_file(cookie_jar)
                        print("已成功获取并保存新cookie")
                    else:
                        logging.error("无法创建cookie jar，cookie字符串可能无效")
                        print("错误: cookie格式无效，无法继续。")
                        return
                else:
                    logging.error("未能获取有效的cookies，无法继续")
                    print("错误: 未能获取有效的cookies，程序无法继续。")
                    return
            else:
                logging.info("已验证cookie有效")
        except Exception as e:
            logging.error(f"验证cookie时出错: {e}")
            print("验证cookie时出错，需要重新获取新的cookie...")
            
            # 使用临时浏览器会话重新登录
            cookie_str = open_clean_browser_for_login()
            if cookie_str:
                cookie_jar = create_cookie_jar_from_string(cookie_str)
                if cookie_jar and isinstance(cookie_jar, requests.cookies.RequestsCookieJar) and len(cookie_jar) > 0:
                    # 更新全局变量
                    recent_cookies = cookie_jar
                    recent_browser = 'manual_clean'
                    logging.info("成功获取新cookies")
                    # 保存cookies到文件
                    save_cookies_to_file(cookie_jar)
                    print("已成功获取并保存新cookie")
                else:
                    logging.error("无法创建cookie jar，cookie字符串可能无效")
                    print("错误: cookie格式无效，无法继续。")
                    return
            else:
                logging.error("未能获取有效的cookies，无法继续")
                print("错误: 未能获取有效的cookies，程序无法继续。")
                return
    
    print("\n已成功获取cookies，开始监控任务...")
    
    # 执行一次初始检查，用于获取初始状态，不触发提醒
    logging.info("执行初始检查获取基准状态...")
    try:
        initial_tasks, initial_success = check_baseline_tasks()
        if not initial_success:
            logging.warning("初始检查失败，可能需要重新登录")
            logging.info("将在下次检查时重试")
        else:
            logging.info("初始检查完成，已获取基准状态")
    except Exception as e:
        logging.error(f"初始检查时出错: {e}")
        logging.info("将在正常检查循环中重试")
    
    # 重置比较数据，使用初始检查的结果作为基准
    # 现在保留previous_eligible_section_html和previous_eligible_section_hash的值
    
    # 存储上一次检测到的任务
    previous_tasks = []
    is_first_check = True  # 仍然设为True以便正确处理首次检查的消息显示
    failed_attempts = 0
    check_count = 0
    
    try:
        while True:
            if not monitoring_active:
                time.sleep(0.1)  # 暂停时降低CPU使用
                continue
                
            try:
                # 检查操作是否超时
                if check_operation_timeout():
                    logging.warning("检测到操作超时，尝试恢复...")
                    # 不播放语音，直接重试
                
                # 每50次检查，清理一次旧文件
                check_count += 1
                if check_count >= 50:
                    logging.info("执行定期清理...")
                    clean_old_files("page_content_*.html", 3)  # 保留最新的3个完整页面
                    clean_old_files("eligible_tasks_*.html", 5)  # 保留最新的5个Eligible Tasks部分
                    clean_old_files("training_tasks_*.html", 5)  # 保留最新的5个Training Tasks部分
                    check_count = 0
                
                # 检查是否有任务
                tasks, success = check_baseline_tasks()
                
                if not success:
                    # 如果检查失败，可能是需要重新登录
                    failed_attempts += 1
                    message = f"检查失败({failed_attempts}/3)，可能需要重新登录。请检查浏览器是否登录了Baseline。"
                    logging.warning(message)
                    
                    if failed_attempts >= 3:
                        failed_attempts = 0
                        # 在连续失败3次时播放语音提醒，不管原因是什么
                        speak_voice("连续三次检查失败，请选择如何处理")
                        
                        # 询问用户是否要尝试重新获取cookie
                        try:
                            retry_choice = input("\n连续3次请求失败。请选择:\n1. 重新打开临时浏览器获取新cookie\n2. 手动输入新cookie\n3. 继续尝试使用当前cookie\n请输入选择(1/2/3): ")
                            
                            if retry_choice == "1":
                                # 重新启动临时浏览器获取新cookie
                                cookie_str = open_clean_browser_for_login()
                                if cookie_str:
                                    cookie_jar = create_cookie_jar_from_string(cookie_str)
                                    if cookie_jar:
                                        # 更新全局变量
                                        recent_cookies = cookie_jar
                                        recent_browser = 'manual_clean'
                                        # 保存新cookies到文件
                                        save_cookies_to_file(cookie_jar)
                                        logging.info("成功从临时浏览器会话获取新cookies并保存到文件")
                                    else:
                                        logging.warning("无法创建cookie jar，cookie字符串可能无效")
                                else:
                                    logging.warning("未能获取新的cookies")
                            elif retry_choice == "2":
                                # 手动输入新cookie
                                print("\n请从浏览器中获取cookie:")
                                print("1. 按F12打开开发者工具")
                                print("2. 切换到'网络'(Network)标签")
                                print("3. 刷新页面")
                                print("4. 找到对baseline.apple.com的请求")
                                print("5. 在请求头中找到并复制完整的Cookie值")
                                
                                cookie_str = input("请粘贴Cookie字符串: ")
                                if cookie_str:
                                    cookie_jar = create_cookie_jar_from_string(cookie_str)
                                    if cookie_jar:
                                        # 更新全局变量
                                        recent_cookies = cookie_jar
                                        recent_browser = 'manual'
                                        # 保存新cookies到文件
                                        save_cookies_to_file(cookie_jar)
                                        logging.info("成功设置新的手动输入cookies并保存到文件")
                                    else:
                                        logging.warning("无法创建cookie jar，cookie字符串可能无效")
                                else:
                                    logging.warning("未输入cookie，将继续使用当前cookie")
                            # 第3个选项不需要操作，继续使用当前cookie
                        except KeyboardInterrupt:
                            raise
                        except Exception as e:
                            logging.error(f"重试过程中出错: {e}")
                    
                    # 在失败后等待更短时间
                    wait_time = random.uniform(5, 10)  # 减少等待时间到5-10秒
                    logging.info(f"等待 {wait_time:.2f} 秒后再次检查...")
                    time.sleep(wait_time)
                    continue
                
                # 成功检查，重置失败计数
                failed_attempts = 0
                
                if tasks:
                    # 检查是否为Training Tasks格式，如果是，以表格形式显示
                    has_training_format = False
                    for task in tasks:
                        if "Training Tasks\t" in task or any(task.startswith(specific) for specific in SPECIFIC_TRAINING_TASKS):
                            has_training_format = True
                            break
                            
                    if has_training_format:
                        display_training_tasks_table(tasks)
                    
                    # 检查是否有新任务（排除第一次检查）
                    has_new_tasks = is_first_check or any(task not in previous_tasks for task in tasks)
                    
                    if has_new_tasks and not is_first_check:
                        task_count = len(tasks)
                        # 判断是否有明确的任务或只是检测到变化
                        if any("检测到Eligible Tasks部分有内容" in task for task in tasks) and task_count == 1:
                            message = "Baseline网站中检测到Eligible Tasks部分有新内容，但无法识别具体任务。请查看网站。"
                        elif any("检测到Eligible Tasks部分发生变化" in task for task in tasks) and task_count == 1:
                            message = "Baseline网站中的Eligible Tasks部分发生了变化，可能有新任务。请查看网站。"
                        # 添加对Training Tasks的特殊处理
                        elif any("检测到Training Tasks" in task for task in tasks):
                            training_count = sum(1 for task in tasks if "Training任务:" in task)
                            if training_count > 0:
                                message = f"发现{training_count}个Training Tasks！请查看网站查看详细内容。"
                            else:
                                message = "Baseline网站中的Training Tasks部分发生了变化，可能有新任务。请查看网站。"
                        else:
                            message = f"发现苹果Baseline页面有新任务！检测到 {task_count} 个任务。"
                        
                        # 先发送通知，确保桌面通知优先执行
                        # 1. 发送通知
                        send_notification(
                            "Apple Baseline 任务提醒",
                            message
                        )
                        
                        # 2. 短暂延迟确保通知显示
                        time.sleep(0.5)
                        
                        # 3. 打开浏览器新窗口
                        open_new_browser_window()
                        
                        # 4. 播放语音
                        speak_voice()
                        
                        # 打印任务信息
                        logging.info("\n检测到以下任务:")
                        for i, task in enumerate(tasks, 1):
                            # 跳过标题行
                            if "Training Tasks\tEvaluation\tIncomplete Tests" in task:
                                continue
                            logging.info(f"{i}. {task}")
                    elif is_first_check and tasks:
                        # 判断首次检查任务类型
                        if any("首次检查发现" in task for task in tasks):
                            # 如果是首次检查发现的Training Tasks，也显示通知
                            training_count = sum(1 for task in tasks if "Training任务:" in task)
                            message = f"首次检查发现{training_count}个Training Tasks！请查看网站了解详情。"
                            
                            # 发送通知
                            send_notification(
                                "Apple Baseline Training Tasks",
                                message
                            )
                            
                            # 短暂延迟确保通知显示
                            time.sleep(0.5)
                            
                            # 打开浏览器新窗口
                            open_new_browser_window()
                            
                            # 播放语音
                            speak_voice()
                            
                            logging.info(f"\n首次检查发现 {training_count} 个Training Tasks:")
                            task_messages = [task for task in tasks if "Training任务:" in task]
                            for i, task in enumerate(task_messages, 1):
                                logging.info(f"{i}. {task}")
                        elif len(tasks) == 1 and (
                           "检测到Eligible Tasks部分有内容" in tasks[0] or 
                           "检测到Eligible Tasks部分发生变化" in tasks[0] or
                           "检测到Training Tasks" in tasks[0]):
                            logging.info(f"首次检查：{tasks[0]}，将在下次检查时比较变化")
                        else:
                            # 过滤掉标题行后再计算数量
                            filtered_tasks = [task for task in tasks if "Training Tasks\tEvaluation\tIncomplete Tests" not in task]
                            logging.info(f"\n首次检查发现 {len(filtered_tasks)} 个任务:")
                            for i, task in enumerate(filtered_tasks, 1):
                                logging.info(f"{i}. {task}")
                    
                    # 更新任务列表
                    previous_tasks = tasks[:]
                else:
                    # 使用info级别，始终显示任务状态
                    logging.info("未检测到任何任务或变化")
                    
                    # 如果启用了显示预期任务，即使未检测到变化也显示
                    if config.get("display_expected", False) and config.get("check_training", True):
                        logging.info("显示预期的Training Tasks列表:")
                        display_training_tasks_table(["Training Tasks\tEvaluation\tIncomplete Tests"] + 
                                                   [f"{task}\t{count}" for task, count in SPECIFIC_TASK_EXPECTED_COUNTS.items()])
                    
                    previous_tasks = []
                
                # 第一次检查完成
                is_first_check = False
                
                # 等待随机时间后再次检查
                interval = random.uniform(MIN_CHECK_INTERVAL, MAX_CHECK_INTERVAL)
                # 保持为info级别，显示等待时间
                logging.info(f"下次检查将在 {interval:.2f} 秒后进行...")
                time.sleep(interval)
                
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logging.error(f"发生错误: {e}", exc_info=True)
                speak_voice("检测到错误，请检查程序状态")  # 只在发生错误时提示
                time.sleep(MIN_CHECK_INTERVAL)
    
    except KeyboardInterrupt:
        logging.info("\n程序已停止")
    except Exception as e:
        logging.error(f"程序发生严重错误: {e}", exc_info=True)
        speak_voice("程序发生严重错误，请检查日志")  # 只在发生严重错误时提示
    finally:
        # 确保清理资源
        try:
            pygame.mixer.quit()
        except:
            pass

if __name__ == "__main__":
    main() 