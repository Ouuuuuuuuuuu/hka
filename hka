import streamlit as st
import pandas as pd
import requests
import time
import random
import plotly.express as px
import plotly.graph_objects as go
import datetime
from bs4 import BeautifulSoup
from collections import Counter
import jieba
import jieba.analyse

# --- 页面配置 ---
st.set_page_config(
    page_title="WeChat Insight Pro (Reader Mode)",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 核心爬虫逻辑 ---

class WechatCrawler:
    def __init__(self, token, cookie):
        self.base_url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            "Cookie": cookie
        }
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def search_account(self, query):
        """搜索公众号获取fakeid"""
        search_url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz", "token": self.token, "lang": "zh_CN",
            "f": "json", "ajax": "1", "query": query, "begin": "0", "count": "5",
        }
        try:
            res = self.session.get(search_url, params=params)
            data = res.json()
            return data.get("list", [])
        except Exception as e:
            st.error(f"搜索请求异常: {e}")
            return []

    def fetch_article_list(self, fakeid, pages=3):
        """获取文章列表元数据"""
        all_articles = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for page in range(pages):
            status_text.text(f"📡 正在扫描列表第 {page + 1}/{pages} 页...")
            params = {
                "token": self.token, "lang": "zh_CN", "f": "json", "ajax": "1",
                "action": "list_ex", "fakeid": fakeid, "query": "",
                "begin": str(page * 5), "count": "5", "type": "9",
            }
            try:
                res = self.session.get(self.base_url, params=params)
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
                            "item_idx": item.get("item_idx", 1), # 1为头条，2为次条
                            "copyright_type": item.get("copyright_type", 0) # 1原创
                        })
                else:
                    break
                progress_bar.progress((page + 1) / pages)
                time.sleep(random.uniform(1.5, 3)) # 列表页请求间隔
            except:
                break
        
        progress_bar.empty()
        status_text.empty()
        return all_articles

    def fetch_article_content(self, url):
        """
        深度采集：访问详情页获取正文、作者等信息
        """
        try:
            res = self.session.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "lxml")
            
            # 提取正文文本 (去除HTML标签，保留段落结构)
            content_div = soup.find("div", {"id": "js_content"})
            if content_div:
                # 简单处理：将p标签换行，增强阅读体验
                for p in content_div.find_all('p'):
                    p.insert_after('\n')
                content_text = content_div.get_text().strip()
            else:
                content_text = ""
            
            # 提取作者
            author_tag = soup.find("strong", {"class": "profile_nickname"}) # 旧版
            if not author_tag:
                author_tag = soup.find("a", {"id": "js_name"})
            author = author_tag.get_text().strip() if author_tag else "未知"
            
            # 提取IP属地
            scripts = soup.find_all("script")
            ip_location = "IP未知"
            for script in scripts:
                if script.string and "ip_wording" in script.string:
                    import re
                    match = re.search(r'ip_wording\s*=\s*\{\s*type\s*:\s*2\s*,\s*name\s*:\s*"(.*?)"', script.string)
                    if match:
                        ip_location = match.group(1)
                        break
            
            return content_text, author, ip_location
        except Exception:
            return "", "获取失败", "获取失败"

# --- 数据处理工具 ---

def process_data(articles, crawler=None, fetch_details=False):
    if not articles:
        return pd.DataFrame()
    
    df = pd.DataFrame(articles)
    
    # 时间处理
    df['publish_time'] = pd.to_datetime(df['create_time'], unit='s')
    df['date'] = df['publish_time'].dt.date
    df['year_week'] = df['publish_time'].dt.strftime('%Y-第%W周')
    df['weekday'] = df['publish_time'].dt.weekday
    df['hour'] = df['publish_time'].dt.hour
    
    # 标识处理
    df['position'] = df['item_idx'].apply(lambda x: '头条' if x == 1 else f'次条({x})')
    df['is_original'] = df['copyright_type'].apply(lambda x: '原创' if x == 1 else '转载')
    
    # 深度采集
    if fetch_details and crawler:
        st.info("🐢 正在深度采集全文，速度较慢，请耐心等待...")
        details = []
        bar = st.progress(0)
        for idx, row in df.iterrows():
            content, author, ip = crawler.fetch_article_content(row['link'])
            details.append({
                'content': content,
                'author': author,
                'ip_location': ip
            })
            bar.progress((idx + 1) / len(df))
            time.sleep(random.uniform(0.5, 1.5)) # 必须延时
        
        detail_df = pd.DataFrame(details)
        df = pd.concat([df, detail_df], axis=1)
        bar.empty()
    else:
        df['content'] = ""
        df['author'] = "未采集"
        df['ip_location'] = "-"

    return df

def extract_keywords(df):
    """提取标题和正文中的关键词"""
    text_corpus = "".join(df['title'].astype(str).tolist())
    if 'content' in df.columns and df['content'].any():
        # 如果采集了正文，权重稍微低一点加入语料
        content_corpus = "".join(df['content'].astype(str).tolist())
        text_corpus += content_corpus[:100000] # 限制长度防止过慢
        
    keywords = jieba.analyse.extract_tags(text_corpus, topK=20, withWeight=True)
    return pd.DataFrame(keywords, columns=['word', 'weight'])

# --- 主程序逻辑 ---

with st.sidebar:
    st.title("📖 公众号热点阅读器")
    st.caption("真实数据 · 关键词挖掘 · 沉浸阅读")
    
    with st.expander("🔑 凭证配置 (必填)", expanded=True):
        wx_token = st.text_input("Token", help="URL中的token参数")
        wx_cookie = st.text_area("Cookie", help="F12获取的完整Cookie")
    
    st.divider()
    target_query = st.text_input("🔍 目标公众号", placeholder="输入名称")
    
    col1, col2 = st.columns(2)
    with col1:
        scrape_pages = st.number_input("抓取页数", 1, 10, 2)
    with col2:
        # 既然用户要读全文，这里默认为 True 比较好，但为了防封号还是留选项
        enable_details = st.checkbox("采集正文", value=True, help="必须勾选才能阅读全文")
        
    start_btn = st.button("🚀 开始抓取", type="primary", use_container_width=True)

# --- 主界面 ---

if start_btn and wx_token and wx_cookie and target_query:
    crawler = WechatCrawler(wx_token, wx_cookie)
    
    with st.status("正在建立数据连接...", expanded=True) as status:
        status.write("🔍 定位目标账号...")
        accounts = crawler.search_account(target_query)
        if not accounts:
            status.update(label="未找到账号，请检查Cookie", state="error")
            st.stop()
        
        target = accounts[0]
        status.write(f"✅ 锁定: {target['nickname']}")
        
        status.write("📃 拉取文章列表...")
        raw_list = crawler.fetch_article_list(target['fakeid'], pages=scrape_pages)
        
        if not raw_list:
            status.update(label="未获取到数据", state="error")
            st.stop()

        status.write("🧹 深度采集正文内容...")
        df_res = process_data(raw_list, crawler, fetch_details=enable_details)
        
        status.update(label="数据准备就绪!", state="complete")
        
        st.session_state['data'] = df_res
        st.session_state['account'] = target['nickname']

# --- 看板展示 ---

if 'data' in st.session_state:
    df = st.session_state['data']
    nickname = st.session_state['account']
    
    st.header(f"📰 {nickname} · 深度阅读看板")
    
    # --- Tab 分区 ---
    tab_read, tab_hot, tab_list = st.tabs(["👓 沉浸阅读模式", "🔥 核心热点分析", "📋 文章列表"])
    
    # 1. 沉浸阅读模式
    with tab_read:
        if enable_details and 'content' in df.columns:
            # 拼接标题和日期作为选项
            df['select_label'] = df['date'].astype(str) + " | " + df['title']
            selected_article_label = st.selectbox("选择要阅读的文章:", df['select_label'].tolist())
            
            # 获取选中文章数据
            article = df[df['select_label'] == selected_article_label].iloc[0]
            
            with st.container():
                st.markdown(f"## {article['title']}")
                st.caption(f"作者: {article['author']} | 发布时间: {article['publish_time']} | {article['is_original']} | IP属地: {article['ip_location']}")
                st.divider()
                
                # 正文展示区
                if article['content']:
                    st.markdown(article['content'].replace("\n", "\n\n")) # 增加Markdown换行
                else:
                    st.warning("正文未采集，请确保勾选侧边栏的【采集正文】并重新抓取。")
                    st.markdown(f"[点击跳转原文链接]({article['link']})")
        else:
            st.info("请在左侧侧边栏勾选【采集正文】以启用阅读模式。")

    # 2. 核心热点分析
    with tab_hot:
        st.subheader("词频热点挖掘")
        st.caption("基于文章标题和正文的TF-IDF算法分析，挖掘该公众号近期的核心关注点。")
        
        if not df.empty:
            keywords_df = extract_keywords(df)
            
            c1, c2 = st.columns([2, 1])
            with c1:
                fig = px.bar(keywords_df, x='weight', y='word', orientation='h', 
                             title="核心热词 TOP 20", labels={'weight': '热度权重', 'word': '关键词'},
                             color='weight', color_continuous_scale='Reds')
                fig.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.write("📋 **热词列表**")
                st.dataframe(keywords_df, use_container_width=True)
        else:
            st.write("暂无数据")

    # 3. 文章列表
    with tab_list:
        st.dataframe(
            df[['title', 'date', 'author', 'is_original', 'link']],
            use_container_width=True,
            column_config={
                "link": st.column_config.LinkColumn("原文链接")
            }
        )

else:
    st.info("👈 请在左侧配置抓取参数。为了阅读全文，请务必勾选【采集正文】。")
