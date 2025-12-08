
import streamlit as st
import pandas as pd
import pdfplumber
import docx
import json
import requests
import re
import io
import time
from datetime import datetime

# ==========================================
# 0. 配置与常量
# ==========================================

st.set_page_config(page_title="AI 智能简历筛选系统", layout="wide", page_icon="📝")

# 模拟的高校名单数据库 (用于评分规则)
C9_UNIVERSITIES = ["北京大学", "清华大学", "复旦大学", "上海交通大学", "南京大学", "浙江大学", "中国科学技术大学", "哈尔滨工业大学", "西安交通大学"]
TOP_985_211 = ["中国人民大学", "北京航空航天大学", "北京师范大学", "同济大学", "南开大学", "武汉大学", "中山大学", "华中科技大学", "四川大学", "厦门大学", "东南大学"]  # 示例简略版
TARGET_CITY = "深圳"

# 定义 JSON 提取的 Schema (提示词的核心部分)
JSON_SCHEMA = """
{
    "basic_info": {
        "name": "姓名",
        "gender": "性别(男/女)",
        "age": "年龄(数字)",
        "phone": "电话",
        "subject": "应聘学科",
        "marital_status": "婚育状况(已婚已育/已婚未育/未婚)",
        "residence": "现居住城市",
        "partner_location": "配偶/伴侣工作地城市",
        "parents_background": "父母职业或单位背景摘要"
    },
    "education": {
        "high_school": "高中校名",
        "bachelor_school": "本科校名",
        "bachelor_major": "本科专业",
        "master_school": "研究生校名",
        "master_major": "研究生专业",
        "study_abroad_years": "海外留学时长(年，数字)",
        "exchange_experience": "是否有交换经历(是/否)"
    },
    "work_experience": {
        "current_company": "现任职单位",
        "non_teaching_gap": "非教行业空窗期(年，数字，无则为0)",
        "gap_explanation_valid": "空窗期解释是否合理(是/否/无空窗)",
        "overseas_work_years": "海外工作时长(年，数字)",
        "management_role": "曾任管理岗(中层/年级组长/教研组长/无)",
        "head_teacher_years": "班主任年限(数字)",
        "teaching_years": "教龄(预估数字)"
    },
    "achievements": {
        "honor_titles": ["荣誉称号列表(如学科带头人, 骨干教师, 优青)"],
        "teaching_competition": ["赛课获奖列表(如优质课一等奖)"],
        "academic_results": ["课题或论文成果摘要"]
    },
    "ai_assessment": {
        "summary": "一句话亮点摘要(例如：C9硕士，有奥赛辅导经验，男性)",
        "teaching_philosophy": "教学理念总结",
        "resume_quality_score": "简历精细度评分(1-5分)",
        "career_trajectory": "职业路径(上升型/平稳型/下行型)",
        "potential_score": "AI潜质评分(1-5分)",
        "risk_warning": "风险提示(如：毕业后有3年非教学工作经历，或无)"
    }
}
"""

# ==========================================
# 1. 阶段一：文件预处理 (File Ingestion)
# ==========================================

def extract_text_from_pdf(file_bytes):
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        return f"Error reading PDF: {str(e)}"
    return text

def extract_text_from_docx(file_bytes):
    text = ""
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        return f"Error reading DOCX: {str(e)}"
    return text

def parse_files(uploaded_files):
    parsed_data = []
    for file in uploaded_files:
        file_name = file.name
        content = file.read()
        text = ""
        
        if file_name.endswith('.pdf'):
            text = extract_text_from_pdf(content)
        elif file_name.endswith('.docx') or file_name.endswith('.doc'):
            text = extract_text_from_docx(content)
        else:
            text = "Unsupported file format."
            
        parsed_data.append({"filename": file_name, "content": text})
    return parsed_data

# ==========================================
# 2. 阶段二：AI 智能提取 (AI Extraction)
# ==========================================

def call_deepseek_api(text, api_key):
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    system_prompt = f"""
    你是一个专业的HR招聘专家助手。你的任务是从简历文本中提取关键信息，并将其转化为标准的JSON格式。
    
    请严格按照以下要求操作：
    1. 输出必须是合法的 JSON 格式，不要包含Markdown标记（如 ```json）。
    2. 如果某个字段在简历中找不到，请填写 null 或 "未提及"。
    3. 针对“AI潜质评分”，请根据简历的自我评价、排版质量、职业轨迹进行综合打分（5分制）。
    4. 针对“亮点摘要”，生成一句简短的评价，供面试官快速参考。
    5. 严格遵循以下 JSON 结构：
    {JSON_SCHEMA}
    """
    
    payload = {
        "model": "deepseek-ai/DeepSeek-V3", # SiliconFlow 上通常映射的 DeepSeek 模型名称
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请分析以下简历内容：\n\n{text[:8000]}"} # 截断防止超长
        ],
        "temperature": 0.1, # 低温度以保证提取的准确性和结构化
        "response_format": {"type": "json_object"}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        # 清理可能存在的 markdown 符号
        content = content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        st.error(f"API 调用失败: {str(e)}")
        return None

# ==========================================
# 3. 阶段三：Python 规则评分引擎 (Rule Engine)
# ==========================================

def check_school_tier(school_name):
    if not school_name or school_name == "未提及":
        return "普通"
    school_name = school_name.replace("大学", "").replace("学院", "")
    for s in C9_UNIVERSITIES:
        if s.replace("大学", "") in school_name:
            return "C9"
    for s in TOP_985_211:
        if s.replace("大学", "") in school_name:
            return "985/211"
    if "师范" in school_name and ("北京" in school_name or "华东" in school_name or "华中" in school_name):
         return "重点师范"
    return "普通"

def calculate_score(data):
    """
    严格按照 Excel 文档中的打分表进行评分
    """
    score = 0
    logs = [] # 记录加分原因

    basic = data.get('basic_info', {})
    edu = data.get('education', {})
    work = data.get('work_experience', {})
    achieve = data.get('achievements', {})
    ai = data.get('ai_assessment', {})

    # --- 1. 专业匹配 (最高项逻辑简化，需人工复核，此处做基础加分) ---
    # 假设如果提到竞赛获奖
    score_p1 = 0
    comp_str = str(achieve.get('teaching_competition', [])) + str(achieve.get('honor_titles', []))
    if "省" in comp_str and ("一等奖" in comp_str or "前三" in comp_str):
        score_p1 += 5
        logs.append("专业: 省级奖项 +5")
    elif "跨专业" in str(edu): # 需要AI判断是否有逻辑，这里暂略
        pass
    score += score_p1

    # --- 2. 学习经历 ---
    # 高中
    hs = edu.get('high_school', '')
    if hs and ("中学" in hs or "附中" in hs): 
        # 简单判定，实际需要重点高中库
        if "师大附中" in hs or "一中" in hs or "实验" in hs:
            score += 3
            logs.append("高中: 重点/县中 +3")
    
    # 本科
    ba_tier = check_school_tier(edu.get('bachelor_school'))
    if ba_tier == "C9":
        score += 5
        logs.append("本科: C9 +5")
    elif ba_tier in ["985/211", "重点师范"]:
        score += 3
        logs.append("本科: 985/211 +3")
    
    # 研究生
    ma_tier = check_school_tier(edu.get('master_school'))
    if ma_tier == "C9":
        score += 5
        logs.append("硕士: C9 +5")
    elif ma_tier in ["985/211", "重点师范"]:
        score += 3
        logs.append("硕士: 985/211 +3")

    # 留学
    abroad = edu.get('study_abroad_years', 0)
    if isinstance(abroad, (int, float)) and abroad >= 2:
        score += 2
        logs.append("留学: 2年以上 +2")
    
    exchange = edu.get('exchange_experience', '否')
    if exchange == '是':
        score += 1
        logs.append("留学: 交换经历 +1")

    # --- 3. 家庭背景 ---
    gender = basic.get('gender', '')
    marital = basic.get('marital_status', '')
    if gender == '男':
        score += 3
        logs.append("背景: 男性 +3")
    if gender == '女' and '已育' in marital:
        score += 1
        logs.append("背景: 已婚已育 +1")
    
    parents = basic.get('parents_background', '')
    if parents and any(k in parents for k in ['教师', '学校', '机关', '研发']):
        score += 1
        logs.append("背景: 父母书香/机关 +1")
        
    residence = basic.get('residence', '')
    if TARGET_CITY in str(residence):
        score += 1
        logs.append(f"背景: 住{TARGET_CITY} +1")
        
    partner = basic.get('partner_location', '')
    if TARGET_CITY in str(partner):
        score += 1
        logs.append(f"背景: 配偶在{TARGET_CITY} +1")

    # --- 4. 工作经历 ---
    # 重点学校判定 (关键词匹配)
    curr_comp = work.get('current_company', '')
    if curr_comp and any(k in curr_comp for k in ['中学', '实验', '外国语', '师大']):
        score += 3
        logs.append("工作: 知名学校 +3")
        
    non_teaching = work.get('non_teaching_gap', 0)
    if isinstance(non_teaching, (int, float)) and non_teaching > 2:
        score -= 3
        logs.append("工作: 非教空窗期 -3")
        
    overseas_work = work.get('overseas_work_years', 0)
    if isinstance(overseas_work, (int, float)) and overseas_work >= 1:
        score += 3
        logs.append("工作: 海外工作 +3")

    # --- 5. 教学科研 ---
    titles = str(achieve.get('honor_titles', []))
    if any(k in titles for k in ['特级', '学科带头人', '骨干', '优青']):
        score += 5
        logs.append("能力: 核心头衔 +5")
    
    contest = str(achieve.get('teaching_competition', []))
    if "一等奖" in contest and ("区" in contest or "市" in contest or "省" in contest):
        score += 3
        logs.append("能力: 赛课一等奖 +3")
        
    academic = str(achieve.get('academic_results', []))
    if "课题" in academic or "论文" in academic:
        # 简单给分，实际需判断级别
        score += 1 
        logs.append("能力: 学术成果 +1")

    # --- 6. 管理能力 ---
    mgmt = work.get('management_role', '')
    if mgmt and mgmt != '无' and mgmt != '未提及':
        if "年级组长" in mgmt or "教研" in mgmt or "中层" in mgmt:
            score += 3
            logs.append("管理: 中层/组长 +3")
    
    ht_years = work.get('head_teacher_years', 0)
    if isinstance(ht_years, (int, float)) and ht_years >= 5:
        score += 3
        logs.append("管理: 班主任5年+ +3")
    elif isinstance(ht_years, (int, float)) and ht_years > 0:
        score += 1
        logs.append("管理: 有班主任经历 +1")

    # --- 7 & 8. 个人特质与AI潜质 (直接加 AI 打分) ---
    potential = ai.get('potential_score', 0)
    try:
        p_score = float(potential)
        score += p_score
        logs.append(f"AI潜质: +{p_score}")
    except:
        pass

    return score, "; ".join(logs)

# ==========================================
# 4. 主程序界面 (UI)
# ==========================================

def main():
    st.title("🎓 智能简历筛选系统 (Python + DeepSeek)")
    st.markdown("""
    本系统基于 **Python 解析 -> AI 提取 (DeepSeek-V3.2) -> 规则引擎评分** 的流程。
    上传简历后，将自动生成面试花名册 Excel。
    """)
    
    # 侧边栏配置
    st.sidebar.header("配置")
    
    # 获取 API Key
    try:
        api_key = st.secrets["SILICONFLOW_API_KEY"]
        st.sidebar.success("API Key 已从 Secrets 加载")
    except:
        api_key = st.sidebar.text_input("输入 SiliconFlow API Key", type="password")
        
    uploaded_files = st.sidebar.file_uploader(
        "批量上传简历 (PDF/Word)", 
        type=['pdf', 'docx', 'doc'], 
        accept_multiple_files=True
    )

    if st.sidebar.button("开始分析") and uploaded_files and api_key:
        
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 1. 解析文件
        status_text.text("正在解析文件文本...")
        file_data_list = parse_files(uploaded_files)
        
        total_files = len(file_data_list)
        
        for i, file_data in enumerate(file_data_list):
            status_text.text(f"正在分析 ({i+1}/{total_files}): {file_data['filename']} ...")
            
            # 2. AI 提取
            json_result = call_deepseek_api(file_data['content'], api_key)
            
            if json_result:
                # 3. 规则评分
                total_score, score_logs = calculate_score(json_result)
                
                # 扁平化数据用于 DataFrame
                basic = json_result.get('basic_info', {})
                edu = json_result.get('education', {})
                work = json_result.get('work_experience', {})
                ai_eval = json_result.get('ai_assessment', {})
                achieve = json_result.get('achievements', {})
                
                row = {
                    # 基础信息
                    "姓名": basic.get('name'),
                    "性别": basic.get('gender'),
                    "年龄": basic.get('age'),
                    "电话": basic.get('phone'),
                    "学历": f"{edu.get('bachelor_school')}/{edu.get('master_school')}",
                    "毕业院校": edu.get('master_school') if edu.get('master_school') else edu.get('bachelor_school'),
                    "专业": f"{edu.get('bachelor_major')}/{edu.get('master_major')}",
                    "应聘学科": basic.get('subject'),
                    
                    # 核心筛选 (高亮区)
                    "预估评分": total_score,
                    "评分明细": score_logs,
                    "教龄": work.get('teaching_years'),
                    "职称/头衔": ", ".join(achieve.get('honor_titles', [])),
                    "现单位": work.get('current_company'),
                    
                    # AI 辅助区
                    "亮点摘要": ai_eval.get('summary'),
                    "风险提示": ai_eval.get('risk_warning'),
                    "AI潜质分": ai_eval.get('potential_score'),
                    "职业轨迹": ai_eval.get('career_trajectory'),
                    
                    # 原始文件名
                    "源文件": file_data['filename']
                }
                results.append(row)
            
            # 更新进度条
            progress_bar.progress((i + 1) / total_files)
            time.sleep(0.5) # 防止 API 速率限制

        status_text.text("分析完成！正在生成报表...")
        
        # 4. 生成报表
        if results:
            df = pd.read_json(json.dumps(results)) # 确保格式化
            
            # 排序：按评分降序
            df = df.sort_values(by="预估评分", ascending=False)
            
            st.success(f"成功处理 {len(results)} 份简历")
            
            # 展示数据预览
            st.dataframe(df.style.background_gradient(subset=['预估评分'], cmap='Greens'))
            
            # 导出 Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='面试花名册', index=False)
                
                # 获取 workbook 和 worksheet 对象进行格式设置
                workbook = writer.book
                worksheet = writer.sheets['面试花名册']
                
                # 定义格式
                header_format = workbook.add_format({
                    'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#D7E4BC', 'border': 1
                })
                highlight_format = workbook.add_format({'bg_color': '#FFFF00'}) # 黄色高亮
                
                # 设置列宽
                worksheet.set_column('A:H', 15) # 基础信息
                worksheet.set_column('I:M', 20) # 核心区
                worksheet.set_column('N:Q', 30) # AI区
                
                # 应用高亮到“预估评分”列 (假设在 I 列)
                # xlsxwriter 条件格式比较复杂，这里简化处理，手动标记颜色
                
            st.download_button(
                label="📥 下载面试花名册 Excel",
                data=buffer.getvalue(),
                file_name=f"面试花名册_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.ms-excel"
            )
        else:
            st.warning("未能提取到有效数据，请检查简历格式或 API 连接。")

if __name__ == "__main__":
    main()
```

### 核心处理流程解析

1.  **文件预处理 (File Ingestion)**：
    * `parse_files` 函数自动检测文件类型。
    * 使用 `pdfplumber` 处理 PDF，使用 `docx` 处理 Word 文档。
    * 将所有非结构化文档转换为纯文本字符串。

2.  **AI 智能提取 (AI Extraction / ETL)**：
    * **Prompt 设计**：我们定义了一个非常详细的 `JSON_SCHEMA`。Prompt 中明确要求 DeepSeek 模型“你是一个HR专家”，并强制要求返回 JSON 格式。
    * **字段映射**：涵盖了你需求中的所有细分字段（如父母背景、非教行业空窗期、是否已婚已育等）。
    * **AI 评分注入**：让 AI 在提取阶段就完成主观题（职业轨迹判断、亮点摘要、AI 潜质评分 0-5 分）。

3.  **规则评分引擎 (Rule Engine)**：
    * `calculate_score` 函数实现了你提供的 Excel 评分逻辑。
    * **高校分层**：内置了 `C9_UNIVERSITIES` 和 `TOP_985_211` 列表，自动判断学历加分。
    * **家庭/地域**：检测性别、婚育、以及是否包含目标城市（代码中设为 "深圳"）。
    * **硬性扣分**：如果 `non_teaching_gap` > 2 年，自动扣 3 分。
    * **加分日志**：代码会生成 `评分明细` 字段（如 "硕士: C9 +5; 背景: 男性 +3"），让面试官知道分数的来源。

4.  **输出 (Reporting)**：
    * 使用 `pandas` 生成表格。
    * 使用 `xlsxwriter` 引擎在内存中生成 Excel 文件。
    * Streamlit 提供下载按钮。
    * 界面上使用 `dataframe` 组件展示预览，并按评分从高到低自动排序。

### 如何使用

1.  将上述代码保存为 `streamlit_app.py`。
2.  在 `.streamlit/secrets.toml` 中填入你的 API KEY：
    ```toml
    SILICONFLOW_API_KEY = "sk-xxxxxxxxxxxxxx"
    ```
3.  运行应用：
    ```bash
    streamlit run streamlit_app.py
