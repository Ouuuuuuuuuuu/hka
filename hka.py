import streamlit as st
import pandas as pd
import requests
import time
import random
import os
import sys
import subprocess
import jieba
import matplotlib.pyplot as plt
import collections
import re
import json
from wordcloud import WordCloud
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from io import BytesIO
import base64

# --- 页面基础配置 ---
st.set_page_config(
    page_title="公众号热点分析系统",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 字体管理 (解决中文乱码)
# ==========================================

def get_font_path():
    """
    获取中文字体路径。如果系统没有，尝试下载 SimHei。
    """
    local_font = "SimHei.ttf"
    if os.path.exists(local_font):
        return local_font
    
    system_fonts = [
        "/System/Library/Fonts/PingFang.ttc", # MacOS
        "/System/Library/Fonts/STHeiti Light.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf", # Windows
        "C:\\Windows\\Fonts\\msyh.ttc", 
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", # Linux
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    ]
    for path in system_fonts:
        if os.path.exists(path):
            return path
            
    try:
        url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
        res = requests.get(url, timeout=300)
        with open(local_font, "wb") as f:
            f.write(res.content)
        return local_font
    except:
        pass
        
    return None

font_path = get_font_path()
if font_path:
    import matplotlib.font_manager as fm
    fe = fm.FontEntry(fname=font_path, name='CustomFont')
    fm.fontManager.ttflist.insert(0, fe)
    plt.rcParams['font.sans-serif'] = ['CustomFont']
else:
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 核心工具类
# ==========================================

def clean_wechat_html(html_content):
    if not html_content:
        return "<div style='padding:20px; text-align:center; color:#999'>📭 正文内容为空</div>"
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    content_div = soup.find("div", id="js_content")
    if content_div:
        existing_style = content_div.get('style', '')
        content_div['style'] = existing_style + '; visibility: visible !important; opacity: 1 !important;'
    
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()

    for img in soup.find_all("img"):
        if "data-src" in img.attrs:
            img["src"] = img["data-src"]
        img["referrerpolicy"] = "no-referrer"
        img["style"] = "max-width: 100% !important; height: auto !important; display: block; margin: 10px auto; border-radius: 4px;"

    wrapper = f"""
    <div style="
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        line-height: 1.8;
        color: #333;
        font-size: 16px;
        background-color: #fff;
        padding: 15px;
    ">
        {str(soup)}
    </div>
    """
    return wrapper

def get_smart_stopwords(name_list):
    """
    智能生成屏蔽词：
    1. 基础自称 (本校, 我院...)
    2. 全名 & 分词
    3. 智能简称 (南外, 北大, 深中, 华师)
    """
    stop_tokens = set()
    
    # 0. 基础自称与高频噪音
    self_refs = {'本校', '本院', '我校', '我院', '官微', '官号', '学校', '学院', '官方'}
    stop_tokens.update(self_refs)

    # 常见后缀，用于提取核心词 (清华大学 -> 清华)
    suffixes = ['大学', '学院', '学校', '中学', '小学', '幼儿园', '官方', '公众号', '教育', '集团', '国际']
    
    for name in name_list:
        # 1. 原始全名
        stop_tokens.add(name)
        
        # 2. 结巴分词 (例如 '重庆德普外国语学校' -> '重庆', '德普', '外国语', '学校')
        tokens = jieba.lcut(name)
        for t in tokens:
            if len(t) > 1:
                stop_tokens.add(t)
                
        # 3. 智能去后缀 (例如 '清华大学' -> '清华')
        core_name = name
        for suffix in suffixes:
            core_name = core_name.replace(suffix, "")
        if len(core_name) >= 2:
            stop_tokens.add(core_name)
            
        # 4. 行业特定简称规则
        if len(name) >= 3:
            first_char = name[0] # 取首字 (如 '南', '北', '深')
            
            # 规则A: "X大" (北京大学 -> 北大)
            if name.endswith("大学"):
                stop_tokens.add(first_char + "大")
            
            # 规则B: "X外" (南京外国语学校 -> 南外)
            if "外国语" in name:
                stop_tokens.add(first_char + "外")
                
            # 规则C: "X中" (深圳中学 -> 深中)
            if "中学" in name and "大学" not in name:
                stop_tokens.add(first_char + "中")
                
            # 规则D: "X师" / "X师大" (华南师范大学 -> 华师)
            if "师范" in name:
                stop_tokens.add(first_char + "师")
                stop_tokens.add(first_char + "师大")
                
            # 规则E: "X附" (附属)
            if "附属" in name:
                stop_tokens.add(first_char + "附")

    return stop_tokens

def generate_wordcloud_img(text_data, exclude_words=None):
    """
    生成词云图片对象
    exclude_words: 需要额外屏蔽的词列表
    """
    if not text_data:
        return None, []
        
    f_path = get_font_path()
    words = jieba.lcut(text_data)
    
    # 基础通用屏蔽词 (保留了 用户关心的 "家长", "学生" 等词)
    base_stops = set([
        '的', '了', '和', '是', '就', '都', '而', '及', '与', '在', '为', '对', '等', '篇', 
        '微', '信', '号', '月', '日', '年', '有', '我', '他', '她', '它', '这', '那',
        '我们', '图片', '来源', '原标', '题', '公众', '点击', '阅读', '原文', '下方', '关注',
        '展开', '全文', '视频', '分享', '收藏', '点赞', '在看', '扫码', '识别', '二维码',
        '官方', '平台', '发布', '资讯', '服务', '查看', '更多', '回复', '关键字',
        '学校', '教育', '学院', '大学', '中学', '小学', '幼儿园', '国际', '外国语', '校区' 
    ])
    
    if exclude_words:
        base_stops.update(exclude_words)
    
    filtered_words = [w for w in words if len(w) > 1 and w not in base_stops]
    space_split_text = " ".join(filtered_words)
    
    if not space_split_text.strip():
        return None, []

    try:
        wc = WordCloud(
            font_path=f_path,
            width=1000, 
            height=500,
            background_color='white',
            max_words=150,
            colormap='viridis',
            prefer_horizontal=0.9
        ).generate(space_split_text)
        return wc, filtered_words
    except Exception as e:
        print(f"词云生成失败: {e}")
        return None, []

# ==========================================
# AI 分析模块 (Stream 流式版)
# ==========================================

def call_ai_analysis_stream(data_payload, reasoning_placeholder, report_placeholder, mode="global"):
    """
    调用 SiliconFlow API 进行 AI 分析 (流式输出)
    """
    api_key = st.secrets.get("SILICONFLOW_API_KEY", "sk-lezqyzzxlcnarawzhmyddltuclijckeufnzzktmkizfslcje")
    
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 提示词保持不变
    if mode == "global":
        system_prompt = """你是一位资深的教育行业新媒体数据分析专家。
用户将提供一份JSON格式的汇总数据，包含多个公众号在近期的发文统计、标题列表及提取的高频热词。
请撰写一份【深度热点对比分析报告】。

报告核心维度：
1. **核心议题概览**：分析各公众号近期关注的重点热点话题。
2. **活跃度与策略对比**：对比各账号的发文频率和运营活跃度。
3. **内容风格洞察**：分析各账号的行文风格（如标题党、学术严谨、亲民等）。
4. **总结与建议**：给出优化建议。

请务必在回答开头展示你的【思考过程】(Reasoning Content)，然后再输出最终报告。"""
    else:
        system_prompt = """你是一位资深的教育行业新媒体运营顾问。
用户将提供【单个公众号】近期的发文数据（标题、摘要、热词）。
请撰写一份【单账号运营诊断报告】。

报告核心维度：
1. **人设与风格分析**：基于标题和摘要，分析该账号试图打造什么样的人设？
2. **内容偏好**：他们最喜欢发什么类型的内容？
3. **改进建议**：有哪些标题可以优化？有哪些热点可以结合？

请务必在回答开头展示你的【思考过程】(Reasoning Content)，然后再输出最终报告。"""

    data_json = json.dumps(data_payload, ensure_ascii=False, indent=2)
    
    payload = {
        "model": "Pro/moonshotai/Kimi-K2.5", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"这是数据：\n{data_json}"}
        ],
        "stream": True, # 开启流式
        "temperature": 0.7
    }
    
    # 累计变量
    full_reasoning = ""
    full_content = ""
    
    try:
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=3000) as response:
            if response.status_code != 200:
                return False, f"API Error: {response.status_code} - {response.text}", ""
                
            # 处理流式响应
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        json_str = decoded_line[6:]
                        if json_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(json_str)
                            delta = chunk['choices'][0]['delta']
                            
                            # 1. 捕捉思考过程 (Reasoning)
                            if 'reasoning_content' in delta and delta['reasoning_content']:
                                content_piece = delta['reasoning_content']
                                full_reasoning += content_piece
                                # 实时更新思考框
                                reasoning_placeholder.info(f"**🧠 AI 正在深度思考...**\n\n{full_reasoning}▌")
                            
                            # 2. 捕捉正文内容 (Content)
                            if 'content' in delta and delta['content']:
                                content_piece = delta['content']
                                full_content += content_piece
                                # 思考完成后，思考框显示完整内容（去掉光标），开始更新正文
                                reasoning_placeholder.info(f"**🧠 思考完成**\n\n{full_reasoning}") 
                                report_placeholder.markdown(full_content + "▌")
                                
                        except Exception as e:
                            continue
                            
        # 最终清理光标
        reasoning_placeholder.info(f"**🧠 思考完成**\n\n{full_reasoning}")
        report_placeholder.markdown(full_content)
        return True, full_content, full_reasoning

    except Exception as e:
        return False, f"Request Failed: {str(e)}", ""

def prepare_global_ai_data(df):
    """准备全网分析的数据"""
    summary_data = []
    # 智能屏蔽词
    all_accounts = df['account_name'].unique()
    stop_tokens = get_smart_stopwords(all_accounts)
    base_stops = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '有', '等', '为', '之', '与', '及', '以', '微', '信', '公众', '号', '扫码', '二维码', '关注', '阅读', '原文', '点击', '查看', '更多', '来源', '图片', '视频', '展开', '全文'}
    stop_tokens.update(base_stops)

    for account_name in all_accounts:
        sub_df = df[df['account_name'] == account_name]
        text_content = " ".join(sub_df['title'].tolist() + sub_df['digest'].fillna("").tolist())
        words = jieba.lcut(text_content)
        words = [w for w in words if len(w) > 1 and w not in stop_tokens]
        top_keywords = [w for w, c in collections.Counter(words).most_common(10)]
        
        summary_data.append({
            "公众号名": account_name,
            "发文数": len(sub_df),
            "文章标题": sub_df['title'].tolist(),
            "高频热词": top_keywords
        })
    return summary_data

def prepare_single_ai_data(df, account_name):
    """准备单号分析的数据"""
    sub_df = df[df['account_name'] == account_name]
    return {
        "公众号名": account_name,
        "发文数": len(sub_df),
        "最新发布": str(sub_df['发布时间'].max()),
        "文章列表": [
            {"标题": row['title'], "摘要": row['digest']} 
            for _, row in sub_df.iterrows()
        ]
    }

# ==========================================
# 爬虫类
# ==========================================

class WechatCrawler:
    def __init__(self, token, cookie):
        self.base_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def check_auth(self):
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": "test", "begin": "0", "count": "1"
        }
        try:
            res = self.session.get(url, params=params)
            data = res.json()
            if "base_resp" in data and data["base_resp"]["ret"] != 0:
                return False, f"Token 失效或 Cookie 过期: {data['base_resp']}"
            return True, "验证通过"
        except:
            return False, "网络连接异常"

    def search_account(self, query):
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params, timeout=10)
            data = res.json()
            return data.get("list", [])
        except:
            return []

    def fetch_article_list(self, fakeid, pages=1):
        all_articles = []
        for page in range(pages):
            params = {
                "token": self.token, "lang": "zh_CN", "f": "json", "ajax": "1",
                "action": "list_ex", "fakeid": fakeid, "query": "",
                "begin": str(page * 5), "count": "5", "type": "9",
            }
            try:
                res = self.session.get(self.base_url, params=params, timeout=10)
                data = res.json()
                if "app_msg_list" in data:
                    for item in data["app_msg_list"]:
                        all_articles.append({
                            "aid": item.get("aid"),
                            "title": item.get("title"),
                            "digest": item.get("digest"),
                            "link": item.get("link"),
                            "create_time": item.get("create_time"),
                            "cover": item.get("cover"),
                            "copyright_type": item.get("copyright_type", 0)
                        })
                else:
                    break
                time.sleep(random.uniform(0.5, 1.5))
            except:
                break
        return all_articles

    def fetch_content(self, url):
        try:
            res = self.session.get(url, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
            content_div = soup.find("div", id="js_content")
            
            if content_div:
                final_html = clean_wechat_html(str(soup))
                plain_text = content_div.get_text(strip=True)
            else:
                final_html = clean_wechat_html(res.text)
                plain_text = ""
            
            author_tag = soup.find("strong", {"class": "profile_nickname"}) or soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            return final_html, author, plain_text
        except Exception:
            return "<div>获取失败</div>", "获取失败", ""

# ==========================================
# 自动化登录
# ==========================================

def force_install_chromium():
    try:
        cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except:
        return False

def auto_login_browser():
    status_box = st.empty()
    qr_box = st.empty()
    token = None
    cookie_str = None

    status_box.info("🚀 正在启动自动化引擎 (高清云端模式)...")

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    status_box.warning("⚙️ 正在安装浏览器内核...")
                    if force_install_chromium():
                         status_box.success("✅ 安装成功！重试中...")
                         browser = p.chromium.launch(headless=True)
                    else:
                         return None, None
                else:
                    raise e

            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()

            status_box.info("🔗 正在加载微信登录页...")
            page.goto("https://mp.weixin.qq.com/")
            
            try:
                page.wait_for_selector(".login__type__container__scan", timeout=15000)
            except:
                pass 

            status_box.warning("📱 请使用手机微信扫码 (二维码已放大):")
            
            max_wait = 120
            for i in range(max_wait):
                try:
                    if page.is_closed(): return None, None
                    current_url = page.url
                except: return None, None

                if i % 1.5 == 0 and "token=" not in current_url:
                    try:
                        qr_elem = page.locator(".login__type__container__scan")
                        if qr_elem.count() > 0:
                            screenshot_bytes = qr_elem.screenshot()
                            qr_box.image(screenshot_bytes, caption="📸 请扫码 (实时画面)", width=400)
                        else:
                            screenshot_bytes = page.screenshot()
                            qr_box.image(screenshot_bytes, caption="📸 请扫码 (全屏备用)", width=600)
                    except:
                        pass

                if "token=" in current_url:
                    qr_box.empty()
                    status_box.success(f"✅ 登录成功！")
                    
                    parsed = urlparse(current_url)
                    token = parse_qs(parsed.query).get("token", [""])[0]
                    cookies = context.cookies()
                    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                    time.sleep(1)
                    break
                else:
                    time.sleep(1)
            
            browser.close()
            
    except Exception as e:
        status_box.error(f"❌ 运行错误: {e}")
        return None, None

    return token, cookie_str

# ==========================================
# Streamlit 主界面
# ==========================================

if 'wx_token' not in st.session_state: st.session_state['wx_token'] = ''
if 'wx_cookie' not in st.session_state: st.session_state['wx_cookie'] = ''
if 'all_data' not in st.session_state: st.session_state['all_data'] = None

with st.sidebar:
    st.title("🎓 公众号热点分析 Pro")
    st.caption("Playwright · 词云 · Kimi深度思考")
    st.markdown("---")
    
    if st.button("📢 1. 扫码获取权限", type="primary", use_container_width=True):
        token, cookie = auto_login_browser()
        if token and cookie:
            st.session_state['wx_token'] = token
            st.session_state['wx_cookie'] = cookie
            st.success("权限获取成功！")
            time.sleep(1)
            st.rerun()

    with st.expander("🔑 凭证管理", expanded=True):
        token_input = st.text_input("Token", value=st.session_state['wx_token'])
        cookie_input = st.text_area("Cookie", value=st.session_state['wx_cookie'], height=100)
        
        if token_input != st.session_state['wx_token']: st.session_state['wx_token'] = token_input
        if cookie_input != st.session_state['wx_cookie']: st.session_state['wx_cookie'] = cookie_input

    st.markdown("---")
    targets_input = st.text_area(
        "2. 输入公众号名称", 
        placeholder="支持中文逗号、顿号、空格或换行分隔\n例如：\n清华大学、北京大学，复旦大学",
        height=150
    )
    
    page_count = st.slider("每个号抓取页数 (每页5篇)", 1, 5, 2)
    run_btn = st.button("🚀 3. 开始分析", use_container_width=True)

# --- 主逻辑区 ---

if run_btn:
    if not token_input or not cookie_input:
        st.error("请先获取 Token 和 Cookie！")
        st.stop()
    if not targets_input.strip():
        st.error("请输入至少一个公众号！")
        st.stop()
        
    target_list = re.split(r'[,\s\n，、]+', targets_input.strip())
    target_list = [t for t in target_list if t]
    
    crawler = WechatCrawler(token_input, cookie_input)
    
    all_results = []
    status_container = st.status("正在进行数据采集...", expanded=True)
    progress_bar = st.progress(0)
    
    with status_container:
        if not crawler.check_auth()[0]:
            st.error("权限验证失败，请重新扫码！")
            st.stop()
            
        total_targets = len(target_list)
        for i, target_name in enumerate(target_list):
            st.write(f"🔄 [{i+1}/{total_targets}] 分析: **{target_name}** ...")
            
            accounts = crawler.search_account(target_name)
            if not accounts:
                st.warning(f"⚠️ 未找到: {target_name}，跳过")
                continue
            
            target_account = accounts[0]
            fakeid = target_account['fakeid']
            real_nickname = target_account['nickname']
            
            articles = crawler.fetch_article_list(fakeid, pages=page_count)
            
            if articles:
                st.write(f"   - 抓取正文 ({len(articles)}篇)...")
                for art in articles:
                    html_content, author, plain_text = crawler.fetch_content(art['link'])
                    art['content_html'] = html_content
                    art['plain_text'] = plain_text
                    art['author'] = author
                    art['account_name'] = real_nickname
                    time.sleep(0.5)

            all_results.extend(articles)
            progress_bar.progress((i + 1) / total_targets)
            time.sleep(random.uniform(1.0, 2.0))
            
        status_container.update(label="✅ 采集与分析完成！", state="complete")
    
    if all_results:
        df = pd.DataFrame(all_results)
        df['发布时间'] = pd.to_datetime(df['create_time'], unit='s')
        df['发布日期'] = df['发布时间'].dt.date
        df['类型'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
        st.session_state['all_data'] = df
    else:
        st.warning("未采集到数据。")

# --- 分析看板 ---

if st.session_state['all_data'] is not None:
    df = st.session_state['all_data']
    
    st.divider()
    st.title("📊 公众号新媒体热点看板")
    
    # 4个 Tab
    tab_global_1, tab_global_2, tab_global_3, tab_ai = st.tabs(["☁️ 综合词云", "🏆 影响力排行", "📈 发文趋势", "🤖 全网 AI 热点报告"])
    
    # 全网智能屏蔽词
    all_accounts = df['account_name'].unique()
    global_stop_words = get_smart_stopwords(all_accounts)
    
    with tab_global_1:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("全网·标题词云")
            all_titles = " ".join(df['title'].tolist())
            wc_title, _ = generate_wordcloud_img(all_titles, exclude_words=global_stop_words)
            if wc_title:
                st.image(wc_title.to_array(), use_container_width=True)
            else:
                st.info("数据不足")
                
        with col_g2:
            st.subheader("全网·内容词云")
            all_contents = " ".join(df['plain_text'].fillna("").tolist())
            wc_content, words_list = generate_wordcloud_img(all_contents, exclude_words=global_stop_words)
            if wc_content:
                st.image(wc_content.to_array(), use_container_width=True)
            
            if words_list:
                st.markdown("**🔥 全网 TOP 10 热词:**")
                counts = collections.Counter(words_list)
                top10 = counts.most_common(10)
                
                # UI 美化：使用 Progress Bar 展示 Top 10
                top10_data = pd.DataFrame(top10, columns=['关键词', '频次'])
                max_count = int(top10_data['频次'].max()) if not top10_data.empty else 1
                
                st.dataframe(
                    top10_data,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "关键词": st.column_config.TextColumn("🔥 关键词", width="medium"),
                        "频次": st.column_config.ProgressColumn(
                            "热度指数",
                            format="%d",
                            min_value=0,
                            max_value=max_count,
                            width="large"
                        )
                    }
                )

    with tab_global_2:
        st.caption("注：数据基于本次抓取的样本计算。")
        col_r1, col_r2 = st.columns(2)
        now = pd.Timestamp.now()
        
        with col_r1:
            st.markdown("#### 📅 本周发文榜")
            week_df = df[df['发布时间'] > (now - pd.Timedelta(days=7))]
            if not week_df.empty:
                week_rank = week_df['account_name'].value_counts().reset_index()
                week_rank.columns = ['公众号', '发文数']
                st.dataframe(
                    week_rank, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "发文数": st.column_config.NumberColumn(
                            "本周发文",
                            format="%d 篇"
                        )
                    }
                )
            else:
                st.info("本周无数据")
                
        with col_r2:
            st.markdown("#### 🗓️ 本月发文榜")
            month_df = df[df['发布时间'] > (now - pd.Timedelta(days=30))]
            if not month_df.empty:
                month_rank = month_df['account_name'].value_counts().reset_index()
                month_rank.columns = ['公众号', '发文数']
                st.dataframe(
                    month_rank, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "发文数": st.column_config.NumberColumn(
                            "本月发文",
                            format="%d 篇"
                        )
                    }
                )
            else:
                st.info("本月无数据")

    with tab_global_3:
        st.subheader("全网发布时间分布")
        date_counts = df.groupby('发布日期').size()
        st.line_chart(date_counts)

    # --- 全网 AI 分析 (修改版) ---
    with tab_ai:
        st.subheader("🤖 Kimi-K2.5 深度热点报告 (全网版)")
        st.info("AI 将对比分析所有抓取的公众号数据。")
        
        if st.button("🧠 开始全网 AI 分析", type="primary", key="btn_global_ai"):
            # 1. 准备布局：上方思考区，下方报告区
            st.markdown("### 🧠 深度思考中...")
            reasoning_container = st.empty()  # 思考过程容器
            
            st.markdown("### 📝 分析报告")
            report_container = st.empty()     # 正文报告容器
            
            ai_data = prepare_global_ai_data(df)
            
            # 2. 调用流式分析
            success, report, reasoning = call_ai_analysis_stream(
                ai_data, 
                reasoning_container, 
                report_container, 
                mode="global"
            )
            
            if not success:
                st.error(report)

    st.markdown("---")

    # 2. 个体画像
    st.header("2. 单号深度画像 (Single Account)")
    
    account_list = df['account_name'].unique()
    selected_account = st.selectbox("👉 选择一个公众号查看详情:", account_list)
    
    if selected_account:
        sub_df = df[df['account_name'] == selected_account].copy()
        
        # 针对单个账号生成特定的智能屏蔽词
        account_stop_words = get_smart_stopwords([selected_account])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("总发文数", len(sub_df))
        c2.metric("原创比例", f"{len(sub_df[sub_df['类型']=='原创']) / len(sub_df) * 100:.1f}%" if len(sub_df)>0 else "0%")
        c3.metric("最新发布", str(sub_df['发布日期'].max()))
        
        tab_s1, tab_s2, tab_s3 = st.tabs(["📊 数据分析", "📰 文章列表与阅读", "🧠 AI 单号诊断"])
        
        with tab_s1:
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown("**标题词云**")
                s_titles = " ".join(sub_df['title'].tolist())
                s_wc_t, _ = generate_wordcloud_img(s_titles, exclude_words=account_stop_words)
                if s_wc_t: st.image(s_wc_t.to_array(), use_container_width=True)
                
            with sc2:
                st.markdown("**内容词云**")
                s_content = " ".join(sub_df['plain_text'].fillna("").tolist())
                s_wc_c, s_words = generate_wordcloud_img(s_content, exclude_words=account_stop_words)
                if s_wc_c: 
                    st.image(s_wc_c.to_array(), use_container_width=True)
                    if s_words:
                        st.markdown("**🔥 账号 TOP 10 热词:**")
                        s_counts = collections.Counter(s_words)
                        s_top10 = s_counts.most_common(10)
                        
                        s_top10_df = pd.DataFrame(s_top10, columns=['关键词', '频次'])
                        s_max_count = int(s_top10_df['频次'].max()) if not s_top10_df.empty else 1
                        
                        st.dataframe(
                            s_top10_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "关键词": st.column_config.TextColumn("关键词", width="medium"),
                                "频次": st.column_config.ProgressColumn(
                                    "频次",
                                    format="%d",
                                    min_value=0,
                                    max_value=s_max_count,
                                    width="large"
                                )
                            }
                        )

        with tab_s2:
            col_list, col_read = st.columns([1, 2])
            with col_list:
                st.markdown("##### 文章列表")
                sub_df['label'] = sub_df.apply(lambda x: f"{x['发布日期']} | {x['title']}", axis=1)
                selected_article_label = st.radio(
                    "点击选择文章阅读:",
                    sub_df['label'].tolist(),
                    label_visibility="collapsed"
                )
            
            with col_read:
                if selected_article_label:
                    read_art = sub_df[sub_df['label'] == selected_article_label].iloc[0]
                    st.markdown(f"#### {read_art['title']}")
                    st.caption(f"✍️ {read_art['author']}  |  🕒 {read_art['发布时间']}")
                    st.divider()
                    if 'content_html' in read_art and read_art['content_html']:
                        st.components.v1.html(read_art['content_html'], height=800, scrolling=True)
                    else:
                        st.warning("正文内容为空")
                        
        with tab_s3:
            st.subheader(f"🧠 {selected_account} - 运营诊断报告")
            if st.button("开始单号诊断", type="primary", key=f"btn_single_{selected_account}"):
                # 1. 准备布局
                st.markdown("### 🧠 深度思考中...")
                s_reasoning_container = st.empty()
                
                st.markdown("### 📝 诊断报告")
                s_report_container = st.empty()
                
                single_ai_data = prepare_single_ai_data(df, selected_account)
                
                # 2. 调用流式分析
                success, report, reasoning = call_ai_analysis_stream(
                    single_ai_data, 
                    s_reasoning_container, 
                    s_report_container, 
                    mode="single"
                )
                
                if not success:
                    st.error(report)

else:
    st.info("👈 请在左侧侧边栏操作：扫码 -> 输入公众号 -> 开始分析")
