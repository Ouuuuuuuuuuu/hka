import streamlit as st
import pandas as pd
import docx
import json
import io
import time
import zipfile
import os
import asyncio
import aiohttp
import nest_asyncio
import re  # 用于底层正则提取
import struct # 新增：用于底层解剖二进制流
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple
import hashlib
import pickle
from dataclasses import dataclass

# 应用 nest_asyncio 以支持在 Streamlit 中运行异步代码
nest_asyncio.apply()

# ============================
# 可选依赖加载与状态监测
# ============================
try:
    import fitz  # PyMuPDF
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    st.error("请安装 pymupdf: pip install pymupdf")
    st.stop()

try:
    import docx
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False

try:
    import olefile
    OLEFILE_SUPPORT = True
except ImportError:
    OLEFILE_SUPPORT = False

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    RAR_SUPPORT = False

try:
    import py7zr
    SEVENZ_SUPPORT = True
except ImportError:
    SEVENZ_SUPPORT = False

# OCR 支持（可选）- 使用DeepSeek OCR API via 硅基流动
OCR_SUPPORT = True  # 默认启用DeepSeek OCR
OCR_ENGINE = "deepseek"  # 默认使用deepseek-ocr

try:
    import pytesseract
    from PIL import Image
    # 测试OCR是否真正可用
    try:
        pytesseract.get_tesseract_version()
        TESSERACT_SUPPORT = True
    except Exception:
        TESSERACT_SUPPORT = False
except ImportError:
    TESSERACT_SUPPORT = False

# ============================
# 配置区
# ============================
st.set_page_config(
    page_title="智能简历筛选系统 v4.0", 
    layout="wide", 
    page_icon="📄",
    initial_sidebar_state="collapsed"
)

# 可配置参数 - 优化速度
DEFAULT_CONFIG = {
    "target_city": "",
    "max_workers": 20,
    "api_timeout": 60,  # 缩短超时时间
    "enable_cache": True,
    "max_concurrent_api": 100,  # 并发数
    "api_retry": 2,  # 重试次数
}

# 立即初始化所有 session_state 变量
if 'config' not in st.session_state:
    st.session_state.config = DEFAULT_CONFIG.copy()

for key in ['uploaded_files_queue', 'processing', 'final_results', 'failed_files', 'need_review']:
    if key not in st.session_state:
        st.session_state[key] = [] if 'queue' in key or 'results' in key or 'files' in key else False

if not OLEFILE_SUPPORT:
    st.sidebar.warning("未检测到 `olefile` 库，深度 .doc 解析功能已降级。建议执行 `pip install olefile`")

# ============================
# 缓存系统
# ============================
class ResumeCache:
    """基于内存和pickle的缓存系统"""
    def __init__(self, cache_dir: str = ".resume_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]
    
    def get(self, data: bytes) -> Dict:
        try:
            if not st.session_state.config.get('enable_cache', True):
                return None
        except:
            return None
        
        key_hash = self._get_hash(data)
        cache_path = os.path.join(self.cache_dir, f"{key_hash}.pkl")
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    cached = pickle.load(f)
                    if time.time() - cached['timestamp'] < 86400:
                        return cached['data']
            except:
                pass
        return None
    
    def set(self, data: bytes, value: Dict):
        try:
            if not st.session_state.config.get('enable_cache', True):
                return
        except:
            return
        
        key_hash = self._get_hash(data)
        cache_path = os.path.join(self.cache_dir, f"{key_hash}.pkl")
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump({'timestamp': time.time(), 'data': value}, f)
        except:
            pass

cache = ResumeCache()

# ============================
# 终极编码修复：精准解决跨平台与压缩包乱码
# ============================

def fix_garbled_filename(name: str) -> str:
    """
    终极乱码修复算法：严格逆转错乱编码，完美还原回真实中文。
    核心原理：被损坏的其实是解码过程。我们需要将乱码按它错误的编码“反转回字节流”，再按正确的规则重新解剖。
    """
    if not name or not isinstance(name, str):
        return name
        
    # 定义高频错乱映射字典: (底层被强制读取的错误格式 -> 应该使用的真实格式)
    repair_pairs = [
        ('cp437', 'utf-8'),    # 典型：τ«ÇσÄå -> UTF-8 (Mac/Linux 在 Windows 下的无标识解压)
        ('gbk', 'utf-8'),      # 典型：鏉ㄦ湞鏅 -> UTF-8 (纯正UTF-8字节流被误当GBK读取)
        ('latin1', 'utf-8'),   # 常见通用单字节错误读取格式
        ('cp437', 'gbk'),      # 早期 ZIP 默认 CP437，实际是 GBK 编码
        ('latin1', 'gbk'),
        ('mac_roman', 'utf-8'),# Mac 特有错误格式
    ]

    best_result = name
    
    # 评分函数：评估转换结果的“健康度”
    # 规则：有效汉字越多越好，乱码符号（拉丁目、希腊字母、特殊绘图符）越少越好
    def score_text(text: str) -> int:
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fa5')
        garbled_chars = sum(1 for c in text if 
                            ('\u0080' <= c <= '\u024F') or  
                            ('\u0370' <= c <= '\u03FF') or  
                            ('\u2000' <= c <= '\u206F') or  
                            ('\u2500' <= c <= '\u259F'))
        return chinese_chars * 10 - garbled_chars * 5

    best_score = score_text(name)

    # 前置风控：如果原本就是健康的纯英文拼音或纯中文，则拒绝执行转换以免破坏原数据
    if best_score >= 0 and sum(1 for c in name if ('\u0080' <= c <= '\u024F' or '\u0370' <= c <= '\u03FF')) == 0:
        return name

    # 循环尝试严格流逆转
    for encode_as, decode_as in repair_pairs:
        try:
            # 1. 严格双向流校验：反向抽取回原始错误字节流
            raw_bytes = name.encode(encode_as)
            # 2. 重新按正确的编码格式完美解剖
            decoded = raw_bytes.decode(decode_as)
            
            current_score = score_text(decoded)
            
            # 3. 找到更完美、更合理的中文解析结果
            if current_score > best_score:
                best_score = current_score
                best_result = decoded
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    return best_result

def get_zip_filenames_raw(zf: zipfile.ZipFile) -> list:
    """获取ZIP文件名列表，并对无标识的文件名执行深度乱码逆转"""
    result = []
    for info in zf.infolist():
        original = info.filename
        flag_utf8 = (info.flag_bits & 0x800) != 0
        
        # 如果 ZIP 规范内明确标记了 UTF-8 (例如较新版本打包工具)，通常本身就是正常的
        if flag_utf8:
            result.append((original, original))
            continue
        
        # 核心：Python 对无标识文件默认使用 cp437 解码导致了 original 必定乱码，送入修复工厂逆转
        fixed = fix_garbled_filename(original)
        result.append((original, fixed))
    
    return result

# ============================
# DeepSeek OCR 函数 (硅基流动)
# ============================
async def deepseek_ocr_image(image_bytes: bytes, api_key: str, prompt: str = "请识别图片中的所有文字内容，保持原有格式和排版。") -> str:
    """使用DeepSeek OCR API (硅基流动) 识别图片中的文字"""
    import base64
    
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 将图片转换为base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 检测图片格式
    image_format = "png"
    if image_bytes[:2] == b'\xff\xd8':
        image_format = "jpeg"
    elif image_bytes[:4] == b'\x89PNG':
        image_format = "png"
    elif image_bytes[:4] == b'GIF8':
        image_format = "gif"
    elif image_bytes[:4] == b'RIFF':
        image_format = "webp"
    
    payload = {
        "model": "deepseek-ai/DeepSeek-OCR",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{image_format};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return f"DeepSeek OCR失败 {response.status}: {error_text[:200]}"
                
                data = await response.json()
                return data['choices'][0]['message']['content']
    except Exception as e:
        return f"DeepSeek OCR异常: {str(e)}"


def deepseek_ocr_image_sync(image_bytes: bytes, api_key: str, prompt: str = "请识别图片中的所有文字内容，保持原有格式和排版。") -> str:
    """同步版本的DeepSeek OCR"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(deepseek_ocr_image(image_bytes, api_key, prompt))


# ============================
# 文件解析函数
# ============================
@st.cache_data(ttl=3600, show_spinner=False)
def extract_text_from_pdf_cached(file_bytes: bytes, use_ocr: bool = False, api_key: str = None, force_ocr: bool = False) -> str:
    """从PDF提取文本（带缓存），支持OCR"""
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = ""
            image_count = 0
            for page in doc:
                page_text = page.get_text()
                text += page_text + "\n"
                # 检测页面中是否有图片
                image_list = page.get_images()
                if image_list:
                    image_count += len(image_list)
            
            # 如果开启强制OCR，或文本太短/检测到图片且启用了OCR，尝试OCR
            should_ocr = use_ocr and api_key and (force_ocr or len(text.strip()) < 100 or image_count > 0)
            if should_ocr:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                ocr_text = loop.run_until_complete(ocr_pdf_async(file_bytes, api_key))
                if not ocr_text.startswith("OCR失败") and not ocr_text.startswith("OCR未识别") and not ocr_text.startswith("OCR不可用"):
                    if force_ocr:
                        # 强化模式下直接以OCR结果为主
                        text = ocr_text
                    else:
                        text += "\n\n[PDF OCR内容]\n" + ocr_text
                else:
                    text += "\n\n[PDF OCR结果: " + ocr_text + "]"
            
            return text
    except Exception as e:
        return f"PDF解析失败: {str(e)}"

def ocr_pdf(file_bytes: bytes, api_key: str = None) -> str:
    """对PDF进行OCR识别 - 支持DeepSeek OCR和Tesseract"""
    text = ""
    
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page_num, page in enumerate(doc):
                # 将页面渲染为高清图片
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                
                page_text = ""
                # 优先使用DeepSeek OCR API
                if api_key and OCR_ENGINE == "deepseek":
                    page_text = deepseek_ocr_image_sync(
                        img_bytes, 
                        api_key, 
                        prompt="请识别这张简历图片中的所有文字内容，包括姓名、联系方式、教育背景、工作经历等，保持原有格式。"
                    )
                    # 如果DeepSeek失败，尝试tesseract
                    if page_text.startswith("DeepSeek OCR") and TESSERACT_SUPPORT:
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                elif TESSERACT_SUPPORT:
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                else:
                    return "OCR不可用: 未配置API Key或安装Tesseract"
                
                text += f"\n--- 第{page_num+1}页 ---\n" + page_text
        
        return text if text.strip() else "OCR未识别到文字"
    except Exception as e:
        return f"OCR失败: {str(e)}"


async def ocr_pdf_async(file_bytes: bytes, api_key: str = None) -> str:
    """对PDF进行异步并发OCR识别 - 优化多页图片PDF处理速度"""
    text = ""
    
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            semaphore = asyncio.Semaphore(5)  # 单PDF最多5页并发OCR
            
            async def ocr_one_page(page_num: int, page):
                async with semaphore:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_bytes = pix.tobytes("png")
                    
                    page_text = ""
                    if api_key and OCR_ENGINE == "deepseek":
                        page_text = await deepseek_ocr_image(
                            img_bytes,
                            api_key,
                            prompt="请识别这张简历图片中的所有文字内容，包括姓名、联系方式、教育背景、工作经历等，保持原有格式。"
                        )
                        if page_text.startswith("DeepSeek OCR") and TESSERACT_SUPPORT:
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                    elif TESSERACT_SUPPORT:
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                    else:
                        return page_num, "OCR不可用"
                    
                    return page_num, page_text
            
            tasks = [ocr_one_page(i, page) for i, page in enumerate(doc)]
            page_results = await asyncio.gather(*tasks)
            page_results.sort(key=lambda x: x[0])
            
            for page_num, page_text in page_results:
                if page_text != "OCR不可用":
                    text += f"\n--- 第{page_num+1}页 ---\n" + page_text
        
        return text if text.strip() else "OCR未识别到文字"
    except Exception as e:
        return f"OCR失败: {str(e)}"


def extract_images_from_docx(file_bytes: bytes) -> List[bytes]:
    """从DOCX文件中提取图片"""
    images = []
    try:
        import zipfile
        from io import BytesIO
        
        # DOCX实际上是zip文件
        with zipfile.ZipFile(BytesIO(file_bytes), 'r') as zf:
            for name in zf.namelist():
                if name.startswith('word/media/'):
                    images.append(zf.read(name))
    except Exception:
        pass
    return images


def ocr_docx_images(file_bytes: bytes, api_key: str = None) -> str:
    """对DOCX中的图片进行OCR识别"""
    if not api_key:
        return ""
    
    images = extract_images_from_docx(file_bytes)
    if not images:
        return ""
    
    ocr_texts = []
    for i, img_bytes in enumerate(images[:10]):  # 最多处理10张图片
        try:
            text = deepseek_ocr_image_sync(
                img_bytes,
                api_key,
                prompt="请识别这张图片中的所有文字内容，如果是简历内容请完整提取。"
            )
            if not text.startswith("DeepSeek OCR"):
                ocr_texts.append(f"[图片{i+1}]\n{text}")
        except Exception:
            continue
    
    return "\n\n".join(ocr_texts)

def extract_text_from_pdf(file_bytes: bytes, use_ocr: bool = False, api_key: str = None, force_ocr: bool = False) -> str:
    """优先从缓存获取PDF解析结果"""
    cached = cache.get(file_bytes)
    if cached and 'pdf_text' in cached:
        return cached['pdf_text']
    
    result = extract_text_from_pdf_cached(file_bytes, use_ocr, api_key, force_ocr)
    cache.set(file_bytes, {'pdf_text': result})
    return result


# ==========================================
# 终极融合版：DOCX/DOC 解析
# 结合了 OLE2底层穿透 与 原有的降级回退机制
# ==========================================
def extract_text_from_docx(file_bytes: bytes, file_name: str = "", use_ocr: bool = False, api_key: str = None) -> str:
    """终极增强版 DOCX/DOC 解析：多路并发降级机制处理"""
    text = ""
    
    # 【路口1】处理现代 .docx 格式 (高精度保持段落与表格的顺序)
    if DOCX_SUPPORT and file_name.lower().endswith('.docx'):
        try:
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            doc = docx.Document(io.BytesIO(file_bytes))
            for child in doc.element.body.iterchildren():
                if isinstance(child, CT_P):
                    p = Paragraph(child, doc)
                    if p.text.strip(): text += p.text.strip() + "\n"
                elif isinstance(child, CT_Tbl):
                    table = Table(child, doc)
                    text += "\n"
                    for i, row in enumerate(table.rows):
                        row_data = [cell.text.replace('\n', ' ').replace('\r', '').replace('|', '｜').strip() for cell in row.cells]
                        text += "| " + " | ".join(row_data) + " |\n"
                        if i == 0: text += "|" + "|".join(["---"] * len(row.cells)) + "|\n"
                    text += "\n"
            if len(text.strip()) > 50: 
                return text
        except Exception: pass
    
    # 【路口1.5】图片背景 DOCX 的 OCR 处理（将 DOCX 渲染为图片后识别）
    if use_ocr and api_key and len(text.strip()) < 100 and file_name.lower().endswith('.docx') and PDF_SUPPORT:
        try:
            ocr_text = ""
            with fitz.open(stream=file_bytes, filetype="docx") as doc:
                for page_num, page in enumerate(doc):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_bytes = pix.tobytes("png")
                    page_text = deepseek_ocr_image_sync(
                        img_bytes,
                        api_key,
                        prompt="请识别这张简历图片中的所有文字内容，包括姓名、联系方式、教育背景、工作经历等，保持原有格式。"
                    )
                    if page_text.startswith("DeepSeek OCR") and TESSERACT_SUPPORT:
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        page_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                    if not page_text.startswith("DeepSeek OCR") and not page_text.startswith("OCR"):
                        ocr_text += f"\n--- 第{page_num+1}页 ---\n" + page_text
            if ocr_text.strip():
                return ocr_text
        except Exception as e:
            text += f"\n[DOCX OCR尝试失败: {str(e)}]"

    # 【路口2】核心增强：利用 olefile 定向解剖原生 .doc (OLE2格式)
    if file_name.lower().endswith('.doc') and OLEFILE_SUPPORT:
        bio = io.BytesIO(file_bytes)
        try:
            if olefile.isOleFile(bio):
                with olefile.OleFileIO(bio) as ole:
                    meta_lines = []
                    # A. 提取隐藏元数据 (背调辅助)
                    try:
                        meta = ole.get_metadata()
                        if meta.author: meta_lines.append(f"作者: {meta.author.decode('utf-8','ignore') if isinstance(meta.author, bytes) else meta.author}")
                        if meta.creating_application: meta_lines.append(f"应用: {meta.creating_application.decode('utf-8','ignore') if isinstance(meta.creating_application, bytes) else meta.creating_application}")
                        if meta.last_printed: meta_lines.append(f"最后打印日期: {meta.last_printed}")
                    except: pass
                    
                    header = "【文档元数据】\n" + "\n".join(meta_lines) + "\n\n【正文提取】\n" if meta_lines else ""
                    
                    # B. 定向提取 WordDocument 数据流（绕过图片、对象池）
                    if ole.exists('WordDocument'):
                        stream = ole.openstream('WordDocument')
                        raw_data = stream.read()
                        
                        # 解析 FIB (File Information Block) 指针实现物理级穿透
                        if len(raw_data) > 0x20:
                            wIdent = struct.unpack('<H', raw_data[0:2])[0]
                            if wIdent == 0xA5EC: # 合法DOC特征码
                                fcMin = struct.unpack('<I', raw_data[0x18:0x1C])[0]
                                mac = struct.unpack('<I', raw_data[0x1C:0x20])[0]
                                
                                if fcMin < len(raw_data) and mac <= len(raw_data) and fcMin < mac:
                                    text_data = raw_data[fcMin:mac]
                                    # 智能解码：UTF-16LE 对应 Word 的 Unicode 存储，GB18030 对应旧版 ANSI
                                    try:
                                        decoded = text_data.decode('utf-16le', errors='ignore')
                                    except:
                                        decoded = text_data.decode('gb18030', errors='ignore')
                                    
                                    # 表格结构重建：Word 内部 \x07 为单元格界限
                                    decoded = decoded.replace('\x07\x07', ' |\n| ').replace('\x07', ' | ').replace('\r', '\n')
                                    # 去噪：剥离不可见字符
                                    decoded = re.sub(r'[\x00-\x06\x08\x0B\x0C\x0E-\x1F]', '', decoded)
                                    
                                    if len(decoded.strip()) > 50:
                                        return header + decoded.strip()
        except Exception: pass

    # 【路口3】备用机制：处理服务器级别的旧版 .doc 格式 (借助 antiword)
    if file_name.lower().endswith('.doc'):
        import subprocess
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            result = subprocess.run(['antiword', tmp_path], capture_output=True, text=True, timeout=10)
            os.unlink(tmp_path)
            if result.returncode == 0 and len(result.stdout.strip()) > 50:
                return result.stdout
        except Exception:
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass

    # 【路口4】终极降级特种部队：纯 Python 暴力穿透法
    try:
        best_text = ""
        
        # 4.1 尝试识别从招聘平台导出的“伪装 DOC” (实质为 MHT/HTML)
        for enc in ['utf-8', 'gbk', 'gb18030']:
            try:
                decoded_text = file_bytes.decode(enc)
                if '<html' in decoded_text.lower() or 'xmlns:w=' in decoded_text.lower():
                    cleaned_html = re.sub(r'<style.*?>.*?</style>', '', decoded_text, flags=re.IGNORECASE|re.DOTALL)
                    cleaned_html = re.sub(r'<script.*?>.*?</script>', '', cleaned_html, flags=re.IGNORECASE|re.DOTALL)
                    cleaned_html = re.sub(r'<[^>]+>', ' | ', cleaned_html)
                    cleaned_html = re.sub(r'(\s*\|\s*)+', ' | ', cleaned_html)
                    if len(cleaned_html.strip()) > len(best_text):
                        best_text = cleaned_html.strip()
            except: pass

        # 4.2 真正的 .doc 二进制流盲测暴力重组 (兜底方案)
        for enc in ['utf-16le', 'gbk', 'gb18030', 'utf-8']:
            try:
                raw_text = file_bytes.decode(enc, errors='ignore')
                cleaned = re.sub(r'[\x00-\x06\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', raw_text)
                cleaned = cleaned.replace('\u0007', ' | ').replace('\r', '\n')
                cleaned = re.sub(r' {2,}', ' ', cleaned)
                cleaned = re.sub(r'\|\s*\|', '|', cleaned)
                cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
                
                zh_count = len(re.findall(r'[\u4e00-\u9fa5]', cleaned))
                best_zh_count = len(re.findall(r'[\u4e00-\u9fa5]', best_text))
                
                if zh_count > best_zh_count and len(cleaned.strip()) > 50:
                    best_text = cleaned
            except: continue
        
        if len(best_text.strip()) > 50:
            return best_text
    except Exception: pass

    # 【路口5】最后的退化方案：丢给 Fitz 盲算
    if PDF_SUPPORT:
        try:
            filetype = "doc" if file_name.lower().endswith('.doc') else "docx"
            with fitz.open(stream=file_bytes, filetype=filetype) as doc_fitz:
                text_fitz = ""
                for page in doc_fitz:
                    text_fitz += page.get_text() + "\n"
                if len(text_fitz.strip()) > 50:
                    return text_fitz
        except Exception: pass

    return text if text.strip() else "Word文档解析失败或内容为空"

def is_hidden_file(filename: str) -> bool:
    """检查是否为隐藏文件"""
    basename = os.path.basename(filename)
    if basename.startswith('._'):
        return True
    if basename.startswith('.') or basename.startswith('~'):
        return True
    if basename.lower() in ['thumbs.db', 'desktop.ini', '.ds_store']:
        return True
    return False

def extract_archive_files(file_bytes: bytes, file_name: str, max_size: int = 500 * 1024 * 1024) -> List[Dict]:
    """批量解压压缩文件 - 支持大文件，接入严格逆转错乱编码算法"""
    extracted_files = []
    supported_ext = ('.pdf', '.docx', '.doc')
    
    archive_size = len(file_bytes)
    if archive_size > max_size:
        st.error(f"❌ 压缩包过大 ({archive_size/1024/1024:.0f}MB > {max_size/1024/1024:.0f}MB 上限)")
        return extracted_files
    
    try:
        if file_name.lower().endswith('.zip'):
            # 已清理掉原来外层臃肿的 encodings 无效循环
            zf = zipfile.ZipFile(io.BytesIO(file_bytes))
            
            with zf:
                total_uncompressed = sum(info.file_size for info in zf.infolist())
                if total_uncompressed > max_size * 2:
                    st.warning(f"⚠️ 解压后文件过大 ({total_uncompressed/1024/1024:.0f}MB)")
                
                # 获取应用了终极反向纠错编码的映射列表
                name_mapping = get_zip_filenames_raw(zf)
                
                for original_name, decoded_name in name_mapping:
                    if is_hidden_file(decoded_name):
                        continue
                    
                    if decoded_name.lower().endswith(supported_ext):
                        extracted_files.append({
                            'name': os.path.basename(decoded_name), 
                            'bytes': zf.read(original_name)
                        })
        
        elif file_name.lower().endswith('.rar') and RAR_SUPPORT:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.rar') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                with rarfile.RarFile(tmp_path) as rf:
                    for item in rf.namelist():
                        if is_hidden_file(item):
                            continue
                        if item.lower().endswith(supported_ext):
                            # 使用更强大的全局逆转算法
                            decoded_name = fix_garbled_filename(item)
                            extracted_files.append({
                                'name': os.path.basename(decoded_name), 
                                'bytes': rf.read(item)
                            })
            finally:
                os.unlink(tmp_path)
        
        elif file_name.lower().endswith(('.7z', '.7zip')) and SEVENZ_SUPPORT:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.7z') as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                with py7zr.SevenZipFile(tmp_path, mode='r') as zf:
                    for name, bio in zf.readall().items():
                        if is_hidden_file(name):
                            continue
                        if name.lower().endswith(supported_ext):
                            # 使用更强大的全局逆转算法
                            decoded_name = fix_garbled_filename(name)
                            extracted_files.append({
                                'name': os.path.basename(decoded_name), 
                                'bytes': bio.read()
                            })
            finally:
                os.unlink(tmp_path)
            
    except Exception as e:
        st.error(f"解压失败 {file_name}: {str(e)}")
    
    return extracted_files

# ============================
# 批量文件解析 - 高效并发
# ============================
@dataclass
class ParseResult:
    """解析结果数据结构"""
    filename: str
    content: str
    error: str = None
    file_size: int = 0
    parse_time: float = 0.0

def parse_single_file(item: Dict, use_ocr: bool = False, api_key: str = None, force_ocr: bool = False) -> ParseResult:
    """解析单个文件"""
    start_time = time.time()
    
    try:
        file_name = item.get('name', 'unknown')
        content_bytes = item.get('bytes', b'')
        file_size = len(content_bytes)
        
        cached = cache.get(content_bytes)
        if cached and 'parsed_result' in cached:
            result = cached['parsed_result']
            result.parse_time = time.time() - start_time
            return result
        
        text = ""
        error_msg = None
        
        if file_name.lower().endswith('.pdf'):
            text = extract_text_from_pdf(content_bytes, use_ocr, api_key, force_ocr)
        elif file_name.lower().endswith(('.docx', '.doc')):
            text = extract_text_from_docx(content_bytes, file_name, use_ocr, api_key)
            # 如果docx文本太短且启用了OCR，尝试提取嵌入图片OCR（作为补充）
            if len(text.strip()) < 100 and use_ocr and api_key:
                ocr_text = ocr_docx_images(content_bytes, api_key)
                if ocr_text:
                    text += "\n\n[图片OCR内容]\n" + ocr_text
        else:
            error_msg = "不支持的文件类型"
        
        if len(text) < 50 and not error_msg:
            error_msg = "提取文本过短，可能解析失败"
        
        result = ParseResult(
            filename=file_name,
            content=text,
            error=error_msg,
            file_size=file_size,
            parse_time=time.time() - start_time
        )
        
        cache.set(content_bytes, {'parsed_result': result})
        return result
        
    except Exception as e:
        return ParseResult(
            filename=item.get('name', 'unknown'),
            content="",
            error=str(e),
            parse_time=time.time() - start_time
        )

def parse_files_batch(uploaded_items: List[Dict], progress_callback=None, use_ocr: bool = False, api_key: str = None, force_ocr: bool = False) -> Tuple[List[ParseResult], List[Dict]]:
    """批量文件解析，使用线程池并发处理"""
    parsed_data = []
    failed_files = []
    max_workers = st.session_state.config.get('max_workers', 20)
    
    st.write(f"🔧 启动解析: {len(uploaded_items)} 个文件, {max_workers} 个并发 worker")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {
            executor.submit(parse_single_file, item, use_ocr, api_key, force_ocr): item 
            for item in uploaded_items
        }
        
        for i, future in enumerate(as_completed(future_to_item)):
            try:
                result = future.result()
                
                if result.error:
                    failed_files.append({
                        'name': result.filename, 
                        'error': result.error,
                        'size': result.file_size,
                        'content': result.content
                    })
                    st.write(f"❌ 解析失败: {result.filename} - {result.error}")
                else:
                    parsed_data.append(result)
                    st.write(f"✓ 解析成功: {result.filename} ({len(result.content)} 字符)")
            except Exception as e:
                item = future_to_item[future]
                failed_files.append({
                    'name': item.get('name', 'unknown'), 
                    'error': str(e),
                    'size': len(item.get('bytes', b'')),
                    'content': ''
                })
                st.write(f"❌ 解析异常: {item.get('name', 'unknown')} - {str(e)}")
            
            if progress_callback:
                progress_callback(i + 1, len(uploaded_items))
    
    st.write(f"📊 解析完成: 成功 {len(parsed_data)}, 失败 {len(failed_files)}")
    return parsed_data, failed_files

# ============================
# 异步API调用 - 优化并发
# ============================
async def call_deepseek_api_async(
    session: aiohttp.ClientSession, 
    text: str, 
    api_key: str
) -> Dict:
    """异步调用DeepSeek API - 单次调用，不带信号量（由调用方控制）"""
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}", 
        "Content-Type": "application/json"
    }
    
    target_city = ""
    try:
        target_city = st.session_state.config.get('target_city', '')
    except:
        pass
    city_context = f"目标城市：{target_city}" if target_city else ""
    
    # 获取当前年份用于年龄计算
    current_year = datetime.now().year
    current_date = datetime.now().strftime("%Y年%m月%d日")
    
    system_prompt = f"""你是一个专业的HR简历分析助手。请从简历文本中提取结构化信息。
{city_context}

【重要提示】今天是{current_date}，当前年份是{current_year}年。计算年龄时必须使用当前年份{current_year}减去出生年份。例如：2005年出生的人，年龄应该是{current_year - 2005}岁。

【重要】学校层次字段（tier）只能从以下选项中选择：
- C9（九校联盟）
- 985
- 211
- 海外名校
- 双一流
- 重点师范
- 普通一本
- 二本
- 专科
- 无法判断（如果不是中国高校）

请提取以下信息并返回JSON格式：
{{
    "basic_info": {{
        "name": "姓名",
        "gender": "性别(男/女)",
        "age": "年龄(数字，根据当前年份{current_year}计算)",
        "subject": "任教学科",
        "marital_status": "婚育状况(已婚已育/已婚未育/未婚/未提及)",
        "residence": "现居住城市",
        "partner_location": "配偶/伴侣工作地城市",
        "parents_background": "父母职业或单位背景摘要"
    }},
    "education": {{
        "high_school_tier": "高中层次（只能填：重点/县中/普通/无法判断）",
        "bachelor_school": "本科学校（只填学校名称，不要专业）",
        "bachelor_tier": "本科层次（只能从上述tier选项中选择）",
        "master_school": "硕士学校（只填学校名称，不要专业）",
        "master_tier": "硕士层次（只能从上述tier选项中选择）",
        "study_abroad_years": "海外留学时长(年，数字，无则为0)",
        "exchange_experience": "是否有交换经历(是/否)"
    }},
    "work_experience": {{
        "current_company": "现工作单位",
        "school_tier": "现单位档次(市重点/知名民办/普通/机构/其他)",
        "non_teaching_gap": "非教行业空窗期(年，数字，无则为0)",
        "overseas_work_years": "海外工作时长(年，数字，无则为0)",
        "management_role": "曾任管理岗(中层/年级组长/教研组长/无)",
        "head_teacher_years": "班主任年限(数字)",
        "teaching_years": "教龄(预估数字)"
    }},
    "achievements": {{
        "honor_titles": ["荣誉称号列表(如学科带头人, 骨干教师, 优青, 特级)"],
        "teaching_competition": ["赛课获奖列表(如优质课一等奖)"],
        "academic_results": ["课题或论文成果摘要"]
    }},
    "ai_assessment": {{
        "summary": "一句话亮点摘要(50字以内)",
        "risk_warning": "风险提示(如有)",
        "potential_score": "AI潜质评分(1-5分，根据简历质量、职业轨迹综合评估)"
    }}
}}"""
    
    truncated_text = text
    if len(text) > 12000:
        truncated_text = text[:6000] + "\n\n[... 中间内容已截断 ...]\n\n" + text[-6000:]
    
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请分析以下简历：\n\n{truncated_text}"}
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"}
    }
    
    try:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                return {"error": f"API错误 {response.status}: {error_text[:200]}"}
            
            data = await response.json()
            content = data['choices'][0]['message']['content']
            
            try:
                parsed = json.loads(content)
                for key in ['basic_info', 'education', 'work_experience', 'achievements', 'ai_assessment']:
                    if key not in parsed:
                        parsed[key] = {}
                # 注入 debug 信息供排查
                parsed['_debug_prompt'] = system_prompt
                parsed['_debug_raw_response'] = content
                return parsed
            except json.JSONDecodeError as e:
                return {"error": f"JSON解析失败: {str(e)}", "raw_content": content[:500], "_debug_prompt": system_prompt, "_debug_raw_response": content}
                
    except asyncio.TimeoutError:
        return {"error": "API请求超时"}
    except Exception as e:
        return {"error": f"请求异常: {str(e)}"}


async def process_batch_async_fast(parsed_results: List[ParseResult], api_key: str, progress_callback=None) -> List[Dict]:
    """
    异步批量处理简历 - 极速版
    真正的同时并发，而不是顺序await
    """
    results = [None] * len(parsed_results)  # 预分配结果列表
    max_concurrent = st.session_state.config.get('max_concurrent_api', 100)
    timeout = aiohttp.ClientTimeout(total=st.session_state.config.get('api_timeout', 60))
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_one(idx: int, parse_result: ParseResult):
        """处理单个简历"""
        async with semaphore:
            start_time = time.time()
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    api_result = await call_deepseek_api_async(session, parse_result.content, api_key)
                
                results[idx] = {
                    'filename': parse_result.filename,
                    'parsed_content': parse_result.content[:200] + "..." if len(parse_result.content) > 200 else parse_result.content,
                    'full_content': parse_result.content,
                    'api_result': api_result,
                    'parse_time': parse_result.parse_time,
                    'api_time': time.time() - start_time
                }
            except Exception as e:
                results[idx] = {
                    'filename': parse_result.filename,
                    'parsed_content': parse_result.content[:200] if len(parse_result.content) > 200 else parse_result.content,
                    'full_content': parse_result.content,
                    'api_result': {"error": str(e)},
                    'parse_time': parse_result.parse_time,
                    'api_time': time.time() - start_time
                }
            
            if progress_callback:
                progress_callback(sum(1 for r in results if r is not None), len(parsed_results))
    
    # 创建所有任务并同时运行
    tasks = [process_one(i, pr) for i, pr in enumerate(parsed_results)]
    await asyncio.gather(*tasks)
    
    return results


# ============================
# 评分算法 - v3.20 合并版（不再区分敏感字段）
# ============================
def calculate_score(data: Dict) -> Tuple[int, str]:
    """
    简历评分算法 - v3.20合并版
    不再区分公开/敏感，统一评分标准
    返回: (总分, 评分详情)
    """
    score = 0
    logs = []
    
    basic = data.get('basic_info', {})
    edu = data.get('education', {})
    work = data.get('work_experience', {})
    achieve = data.get('achievements', {})
    ai = data.get('ai_assessment', {})
    
    def get_num(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
    
    target_city = ""
    try:
        target_city = st.session_state.config.get('target_city', '')
    except:
        pass
    
    # ========== 1. 专业匹配 (+5) ==========
    comp_str = str(achieve.get('teaching_competition', [])) + str(achieve.get('honor_titles', []))
    if "省" in comp_str and ("一等奖" in comp_str or "前三" in comp_str):
        score += 5
        logs.append("专业: 省级奖项 +5")
    
    # ========== 2. 学习经历 (+19 max) ==========
    hs_tier = str(edu.get('high_school_tier', ''))
    if "重点" in hs_tier or "县中" in hs_tier:
        score += 3
        logs.append(f"高中: {hs_tier} +3")
    
    # 本科层次
    b_tier = str(edu.get('bachelor_tier', ''))
    if "C9" in b_tier:
        score += 5
        logs.append("本科: C9 +5")
    elif "985" in b_tier or "海外名校" in b_tier:
        score += 3
        logs.append(f"本科: {b_tier} +3")
    elif "211" in b_tier or "重点师范" in b_tier:
        score += 1
        logs.append(f"本科: {b_tier} +1")
    
    # 硕士层次
    m_tier = str(edu.get('master_tier', ''))
    if "C9" in m_tier:
        score += 5
        logs.append("硕士: C9 +5")
    elif "985" in m_tier or "海外名校" in m_tier:
        score += 3
        logs.append(f"硕士: {m_tier} +3")
    elif "211" in m_tier or "重点师范" in m_tier:
        score += 1
        logs.append(f"硕士: {m_tier} +1")
    
    # 留学经历
    abroad = get_num(edu.get('study_abroad_years'))
    if abroad >= 2:
        score += 2
        logs.append("留学: 2年以上 +2")
    if str(edu.get('exchange_experience', '否')) == '是':
        score += 1
        logs.append("留学: 交换经历 +1")
    
    # ========== 3. 家庭背景 (+7 max) ==========
    gender = str(basic.get('gender', ''))
    if gender == '男':
        score += 3
        logs.append("背景: 男性 +3")
    if gender == '女' and '已育' in str(basic.get('marital_status', '')):
        score += 1
        logs.append("背景: 已婚已育 +1")
    
    parents = str(basic.get('parents_background', ''))
    if any(k in parents for k in ['教师', '学校', '机关', '研发', '公务员']):
        score += 1
        logs.append("背景: 书香/机关家庭 +1")
    
    # 居住情况
    if target_city:
        if target_city in str(basic.get('residence', '')):
            score += 1
            logs.append(f"居住: 住{target_city} +1")
        if target_city in str(basic.get('partner_location', '')):
            score += 1
            logs.append(f"家庭: 配偶在{target_city} +1")
    
    # ========== 4. 工作经历 (+3/-3) ==========
    work_tier = str(work.get('school_tier', ''))
    if "重点" in work_tier or "知名" in work_tier:
        score += 3
        logs.append(f"工作: {work_tier} +3")
    
    # 空窗期扣分
    if get_num(work.get('non_teaching_gap')) > 2:
        score -= 3
        logs.append("工作: 非教空窗期>2年 -3")
    
    # 海外工作
    if get_num(work.get('overseas_work_years')) >= 1:
        score += 3
        logs.append("工作: 海外工作 +3")
    
    # ========== 5. 教学科研 (+9 max) ==========
    titles = str(achieve.get('honor_titles', []))
    if any(k in titles for k in ['特级', '学科带头人', '骨干', '优青']):
        score += 5
        logs.append("科研: 核心称号 +5")
    
    contest = str(achieve.get('teaching_competition', []))
    if "一等奖" in contest and ("区" in contest or "市" in contest or "省" in contest):
        score += 3
        logs.append("教学: 赛课一等奖 +3")
    
    academic = str(achieve.get('academic_results', []))
    if "课题" in academic or "论文" in academic:
        score += 1
        logs.append("学术: 课题/论文 +1")
    
    # ========== 6. 管理能力 (+7 max) ==========
    mgmt = str(work.get('management_role', ''))
    if mgmt and mgmt not in ['无', '未提及', 'None', 'null']:
        if "年级组长" in mgmt or "教研" in mgmt or "中层" in mgmt:
            score += 3
            logs.append("管理: 组长/中层 +3")
    
    ht_years = get_num(work.get('head_teacher_years'))
    if ht_years >= 5:
        score += 3
        logs.append("管理: 班主任5年+ +3")
    elif ht_years > 0:
        score += 1
        logs.append("管理: 班主任经验 +1")
    
    # ========== 7. AI潜质 ==========
    potential = get_num(ai.get('potential_score'))
    if potential > 0:
        score += int(potential)
        logs.append(f"潜质: AI评分 +{int(potential)}")
    
    if not logs:
        logs.append("未匹配评分条件")
    
    return score, "; ".join(logs)


# ============================
# 结果处理
# ============================
def process_results(api_results: List[Dict], debug_mode: bool = False) -> Tuple[List[Dict], List[Dict]]:
    """处理API结果，生成最终表格 - v3.20合并版"""
    final_results = []
    need_review = []
    
    for result in api_results:
        filename = result['filename']
        api_data = result.get('api_result', {})
        
        if 'error' in api_data:
            row = {
                '文件名': filename,
                '处理状态': '失败',
                '错误信息': api_data['error'],
            }
            if debug_mode:
                row['_debug_extracted_text'] = result.get('full_content', result.get('parsed_content', ''))
                row['_debug_prompt'] = api_data.get('_debug_prompt', '')
                row['_debug_raw_response'] = api_data.get('_debug_raw_response', '')
            final_results.append(row)
            continue
        
        basic = api_data.get('basic_info', {})
        edu = api_data.get('education', {})
        work = api_data.get('work_experience', {})
        achieve = api_data.get('achievements', {})
        ai_eval = api_data.get('ai_assessment', {})
        
        total_score, score_logs = calculate_score(api_data)
        
        # 检查是否需要人工复核
        needs_review = False
        review_fields = []
        for field_name, key in [('姓名', 'name'), ('性别', 'gender'), ('学科', 'subject')]:
            val = basic.get(key, '')
            if not val or val in ['null', 'None', '']:
                needs_review = True
                review_fields.append(field_name)
        
        # v3.20 完整字段（删除敏感字样）
        row = {
            '文件名': filename,
            '处理状态': '需复核' if needs_review else '成功',
            # 基本信息
            '姓名': basic.get('name', ''),
            '性别': basic.get('gender', ''),
            '年龄': basic.get('age', ''),
            '任教学科': basic.get('subject', ''),
            '婚姻状况': basic.get('marital_status', ''),
            '现居地': basic.get('residence', ''),
            # 教育背景
            '高中层次': edu.get('high_school_tier', ''),
            '本科学校': edu.get('bachelor_school', ''),
            '本科层次': edu.get('bachelor_tier', ''),
            '硕士学校': edu.get('master_school', ''),
            '硕士层次': edu.get('master_tier', ''),
            '海外留学': edu.get('study_abroad_years', ''),
            '交换经历': edu.get('exchange_experience', ''),
            # 工作经历
            '现工作单位': work.get('current_company', ''),
            '单位档次': work.get('school_tier', ''),
            '教龄': work.get('teaching_years', ''),
            '班主任年限': work.get('head_teacher_years', ''),
            '管理职务': work.get('management_role', ''),
            '非教空窗': work.get('non_teaching_gap', ''),
            '海外工作': work.get('overseas_work_years', ''),
            # 成就荣誉
            '荣誉称号': ', '.join(api_data.get('achievements', {}).get('honor_titles', [])) if isinstance(api_data.get('achievements', {}).get('honor_titles'), list) else str(api_data.get('achievements', {}).get('honor_titles', '')),
            '教学竞赛': ', '.join(api_data.get('achievements', {}).get('teaching_competition', [])) if isinstance(api_data.get('achievements', {}).get('teaching_competition'), list) else str(api_data.get('achievements', {}).get('teaching_competition', '')),
            '学术成果': ', '.join(api_data.get('achievements', {}).get('academic_results', [])) if isinstance(api_data.get('achievements', {}).get('academic_results'), list) else str(api_data.get('achievements', {}).get('academic_results', '')),
            # 评分（合并版）
            '综合评分': total_score,
            '评分详情': score_logs,
            # AI评估
            'AI评语': ai_eval.get('summary', ''),
            '风险提示': ai_eval.get('risk_warning', ''),
            'AI潜质分': ai_eval.get('potential_score', ''),
            # 家庭信息
            '配偶工作地': basic.get('partner_location', ''),
            '父母背景': basic.get('parents_background', ''),
            '需复核字段': ','.join(review_fields) if needs_review else ''
        }
        
        if debug_mode:
            row['_debug_extracted_text'] = result.get('full_content', result.get('parsed_content', ''))
            row['_debug_prompt'] = api_data.get('_debug_prompt', '')
            row['_debug_raw_response'] = api_data.get('_debug_raw_response', '')
        
        final_results.append(row)
        if needs_review:
            need_review.append(row)
    
    return final_results, need_review


# ============================
# 主界面
# ============================
def main():
    st.title("🎓 智能简历筛选系统 v4.0")
    st.caption("📊 7大维度评分 | ⚡ 极速异步处理 | 🚀 真100并发 | 🔧 OLE2底层穿透解析")
    
    # 初始化
    for key in ['uploaded_files_queue', 'processing', 'final_results', 'failed_files', 'need_review']:
        if key not in st.session_state:
            st.session_state[key] = [] if 'queue' in key or 'results' in key or 'files' in key else False
    
    # API Key检查
    try:
        api_key = st.secrets["SILICONFLOW_API_KEY"]
    except:
        st.error("🔐 请在 `.streamlit/secrets.toml` 中配置 SILICONFLOW_API_KEY")
        st.code('[secrets]\nSILICONFLOW_API_KEY = "your-api-key"')
        st.stop()
    
    # ========== 文件上传区 ==========
    st.subheader("📁 文件上传")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        all_files = st.file_uploader(
            "上传简历文件或压缩包（支持 PDF, DOCX, DOC, ZIP, RAR, 7Z）", 
            type=['pdf', 'docx', 'doc', 'zip', 'rar', '7z', '7zip'],
            accept_multiple_files=True
        )
    with col2:
        # OCR选项
        use_ocr = st.checkbox("启用OCR（识别图片型PDF/DOCX）", value=False)
        if use_ocr:
            st.success(f"✅ DeepSeek OCR已就绪")
            if TESSERACT_SUPPORT:
                st.caption("📎 本地Tesseract作为备用")
        
        # 强化读取模式
        force_ocr = st.checkbox("🔥 强化读取模式", value=False, help="开启后所有PDF强制走OCR，适用于文字层缺失或部分信息无法识别的PDF")
        
        # Debug模式
        debug_mode = st.checkbox("🐛 Debug Mode", value=False, help="开启后在导出的Excel中附带原始解析文本和API请求/响应记录")
        
        # 显示缓存状态
        if st.session_state.config.get('enable_cache', True):
            st.caption("💾 缓存已启用")
    
    # 添加到队列
    new_count = 0
    if all_files:
        existing_names = [qf['name'] for qf in st.session_state.uploaded_files_queue]
        
        for f in all_files:
            if f.name in existing_names:
                continue
                
            if f.name.lower().endswith(('.zip', '.rar', '.7z', '.7zip')):
                with st.spinner(f"解压 {f.name}..."):
                    extracted = extract_archive_files(f.read(), f.name)
                    for ef in extracted:
                        if ef['name'] not in existing_names:
                            st.session_state.uploaded_files_queue.append(ef)
                            new_count += 1
                    st.success(f"📦 {f.name}: 提取 {len(extracted)} 个文件")
            else:
                st.session_state.uploaded_files_queue.append({'name': f.name, 'bytes': f.read()})
                new_count += 1
    
    if new_count > 0:
        st.success(f"✅ 新增 {new_count} 个文件，队列共 {len(st.session_state.uploaded_files_queue)} 个")
    
    # 显示队列
    if st.session_state.uploaded_files_queue:
        with st.expander(f"📋 待处理文件列表 ({len(st.session_state.uploaded_files_queue)} 个)", expanded=True):
            cols = st.columns(4)
            for i, f in enumerate(st.session_state.uploaded_files_queue):
                cols[i % 4].text(f"• {f['name'][:30]}..." if len(f['name']) > 30 else f"• {f['name']}")
        
        if st.button("🗑️ 清空队列", type="secondary"):
            st.session_state.uploaded_files_queue = []
            st.rerun()
    
    st.divider()
    
    # ========== 配置面板 ==========
    st.subheader("⚙️ 配置选项")
    
    cfg_col1, cfg_col2, cfg_col3 = st.columns(3)
    
    with cfg_col1:
        target_city = st.text_input(
            "🎯 目标城市",
            value=st.session_state.config.get('target_city', ''),
            placeholder="如：深圳、北京"
        )
        st.session_state.config['target_city'] = target_city
    
    with cfg_col2:
        max_workers = st.number_input("🔧 解析并发数", min_value=1, max_value=50, value=20)
        st.session_state.config['max_workers'] = max_workers
        enable_cache = st.checkbox("💾 启用缓存", value=True)
        st.session_state.config['enable_cache'] = enable_cache
    
    with cfg_col3:
        api_concurrent = st.number_input("⚡ API并发数", min_value=1, max_value=200, value=100,
                                        help="真正的同时并发，不是顺序执行")
        st.session_state.config['max_concurrent_api'] = api_concurrent
        api_timeout = st.number_input("⏱️ API超时(秒)", min_value=10, max_value=300, value=60)
        st.session_state.config['api_timeout'] = api_timeout
    
    st.divider()
    
    # ========== 开始处理按钮 ==========
    if not st.session_state.uploaded_files_queue:
        st.warning("⚠️ 请先上传简历文件")
        start_btn = st.button("🚀 开始批量解析", type="primary", disabled=True)
    else:
        file_count = len(st.session_state.uploaded_files_queue)
        st.info(f"✅ 就绪：{file_count} 个文件待处理 | 预计时间：{max(5, file_count * 2)}-{max(10, file_count * 4)}秒")
        start_btn = st.button("🚀 开始批量解析", type="primary")
    
    # 处理逻辑
    if start_btn and st.session_state.uploaded_files_queue:
        items_to_process = st.session_state.uploaded_files_queue.copy()
        st.session_state.uploaded_files_queue = []
        
        results = process_all_files(items_to_process, api_key, use_ocr, debug_mode, force_ocr)
        
        if results['final_results']:
            st.session_state.final_results = results['final_results']
            st.session_state.need_review = results['need_review']
    
    # 导出按钮
    if st.session_state.final_results:
        output = io.BytesIO()
        df_export = pd.DataFrame(st.session_state.final_results)
        df_export.to_excel(output, index=False)
        output.seek(0)
        st.download_button(
            "📥 导出Excel结果",
            data=output.getvalue(),
            file_name=f"简历筛选结果_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.divider()
    
    # ========== 结果显示 ==========
    if st.session_state.final_results:
        df = pd.DataFrame(st.session_state.final_results)
        
        # 统计卡片
        st.subheader("📊 处理统计")
        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
        with stat_col1:
            st.metric("总简历数", len(df))
        with stat_col2:
            success_count = len(df[df['处理状态'] == '成功'])
            st.metric("成功解析", success_count)
        with stat_col3:
            review_count = len(df[df['处理状态'] == '需复核'])
            st.metric("需复核", review_count)
        with stat_col4:
            avg_score = df['综合评分'].mean() if '综合评分' in df.columns else 0
            max_score = df['综合评分'].max() if '综合评分' in df.columns else 0
            st.metric("平均/最高评分", f"{avg_score:.1f} / {max_score}")
        
        # 评分维度说明
        with st.expander("📋 评分标准说明 (v4.0 - 合并版)"):
            st.markdown("""
            **评分维度（最大约47分）：**
            - 专业匹配：省级教学竞赛一等奖 +5
            - 学习经历：高中重点+3，本科C9+5/985+3/211+1，硕士同本科，留学2年+2，交换+1
            - 家庭背景：男性+3，已婚已育+1，书香/机关家庭+1，住目标城市+1，配偶在目标城市+1
            - 工作经历：重点/知名学校+3，海外工作+3，非教空窗>2年-3
            - 教学科研：核心头衔+5，赛课一等奖+3，学术成果+1
            - 管理能力：中层/组长+3，班主任5年+/有经验+3/+1
            - AI潜质：1-5分
            """)
        
        # 候选人列表
        st.subheader("📋 候选人列表")
        
        display_cols = [
            '文件名', '处理状态', '姓名', '性别', '年龄', '任教学科',
            '本科学校', '本科层次', '硕士学校', '硕士层次',
            '现工作单位', '单位档次', '教龄', '班主任年限', '管理职务',
            '荣誉称号', '教学竞赛',
            '综合评分', '评分详情', 'AI评语', '风险提示'
        ]
        
        # 过滤存在的列
        display_cols = [c for c in display_cols if c in df.columns]
        df_display = df[display_cols].sort_values('综合评分', ascending=False)
        
        try:
            st.dataframe(df_display, use_container_width=True, height=500)
        except Exception as e:
            st.warning(f"表格渲染失败: {str(e)}")
            st.dataframe(df_display.astype(str), use_container_width=True)
        
        # 需复核名单
        if st.session_state.need_review:
            st.subheader("⚠️ 需人工复核")
            review_df = pd.DataFrame(st.session_state.need_review)
            review_display_cols = ['文件名', '姓名', '性别', '任教学科', '需复核字段']
            review_display_cols = [c for c in review_display_cols if c in review_df.columns]
            st.dataframe(review_df[review_display_cols], use_container_width=True)
        
        # Debug 信息不直接展示在UI上，仅保留在导出的Excel中

# ============================
# 处理逻辑
# ============================
def process_all_files(uploaded_items, api_key, use_ocr=False, debug_mode=False, force_ocr=False):
    """处理所有文件的完整流程 - 极速版"""
    total_files = len(uploaded_items)
    results = {
        'parsed_results': [],
        'failed_parse': [],
        'api_results': [],
        'final_results': [],
        'need_review': [],
        'parse_time': 0,
        'ai_time': 0
    }
    
    overall_start = time.time()
    st.info(f"📁 开始处理 {total_files} 个文件...")
    
    try:
        # 阶段1: 文件解析
        with st.spinner(f'📖 解析中 ({total_files} 个文件)...'):
            parse_progress = st.progress(0)
            
            def update_parse_progress(current, total):
                parse_progress.progress(current / total)
            
            start_time = time.time()
            parsed_results, failed_parse = parse_files_batch(
                uploaded_items, 
                update_parse_progress,
                use_ocr,
                api_key,  # 传递api_key用于DeepSeek OCR
                force_ocr
            )
            results['parse_time'] = time.time() - start_time
            results['parsed_results'] = parsed_results
            results['failed_parse'] = failed_parse
            parse_progress.empty()
        
        if not parsed_results:
            st.error("❌ 没有成功解析的文件")
            return results
        
        st.success(f"✅ 解析完成: {len(parsed_results)} 成功, 耗时{results['parse_time']:.1f}s")
        
        # 阶段2: AI分析（真正并发版）
        with st.spinner(f'🤖 AI分析中 ({len(parsed_results)} 份简历，真{st.session_state.config.get("max_concurrent_api", 100)}并发)...'):
            ai_progress = st.progress(0)
            
            def update_ai_progress(current, total):
                ai_progress.progress(current / total, text=f"已完成 {current}/{total}")
            
            start_time = time.time()
            
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 使用新的极速版处理函数
            api_results = loop.run_until_complete(
                process_batch_async_fast(parsed_results, api_key, update_ai_progress)
            )
            results['ai_time'] = time.time() - start_time
            results['api_results'] = api_results
            ai_progress.empty()
        
        total_api_time = sum(r.get('api_time', 0) for r in api_results if r)
        avg_api_time = total_api_time / len(api_results) if api_results else 0
        st.success(f"✅ AI分析完成: {len(api_results)} 个, 总耗时{results['ai_time']:.1f}s, 平均每个{avg_api_time:.1f}s")
        
        # 阶段3: 结果处理
        with st.spinner('📊 生成报告...'):
            final_results, need_review = process_results(api_results, debug_mode)
            # 将解析失败的文件也纳入最终结果，确保用户能看到
            for fail in failed_parse:
                fail_row = {
                    '文件名': fail['name'],
                    '处理状态': '失败',
                    '错误信息': fail['error'],
                }
                if debug_mode:
                    fail_row['_debug_extracted_text'] = fail.get('content', '')
                final_results.append(fail_row)
            results['final_results'] = final_results
            results['need_review'] = need_review
        
        total_time = time.time() - overall_start
        st.success(f"🎉 全部完成！总耗时 {total_time:.1f}s | 成功: {len([r for r in final_results if r['处理状态'] != '失败'])}, 需复核: {len(need_review)}")
        
    except Exception as e:
        st.error(f"❌ 处理过程中出错: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
    
    return results

if __name__ == "__main__":
    main()
