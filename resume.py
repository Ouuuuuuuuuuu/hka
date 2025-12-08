import streamlit as st
import pandas as pd
import docx
import json
import requests
import io
import time
from datetime import datetime
from pypdf import PdfReader  # 使用轻量级库防止部署报错

# ==========================================
# 0. 配置与常量
# ==========================================

st.set_page_config(page_title="AI 智能简历筛选系统 V3.2", layout="wide", page_icon="📝")

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
        "marital_status": "婚育状况(已婚已育/已婚未育/未婚/未提及)",
        "residence": "现居住城市",
        "partner_location": "配偶/伴侣工作地城市",
        "parents_background": "父母职业或单位背景摘要"
    },
    "education": {
        "high_school": "高中校名",
        "high_school_tier": "高中档次(重点高中/县中/普通/未知)",
        "bachelor_school": "本科校名",
        "bachelor_tier": "本科学校层次(必须从以下选项选择其一: C9/985/211/一本/二本/海外名校/海外普通)",
        "bachelor_major": "本科专业",
        "master_school": "研究生校名",
        "master_tier": "研究生学校层次(必须从以下选项选择其一: C9/985/211/一本/二本/海外名校/海外普通)",
        "master_major": "研究生专业",
        "study_abroad_years": "海外留学时长(年，数字)",
        "exchange_experience": "是否有交换经历(是/否)"
    },
    "work_experience": {
        "current_company": "现任职单位",
        "school_tier": "现单位档次(市重点/知名民办/普通/机构/其他)",
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
    """解析 PDF 文件 (使用 pypdf，更稳定)"""
    text = ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        return f"PDF读取错误: {str(e)}"
    return text

def extract_text_from_docx(file_bytes):
    """解析 Word 文件"""
    text = ""
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        return f"Word读取错误: {str(e)}"
    return text

def parse_files(uploaded_files):
    """批量处理上传的文件"""
    parsed_data = []
    for file in uploaded_files:
        try:
            file_name = file.name
            content = file.read()
            text = ""
            
            if file_name.lower().endswith('.pdf'):
                text = extract_text_from_pdf(content)
            elif file_name.lower().endswith(('.docx', '.doc')):
                text = extract_text_from_docx(content)
            else:
                text = "不支持的文件格式"
                
            parsed_data.append({"filename": file_name, "content": text})
        except Exception as e:
            st.error(f"文件 {file.name} 处理失败: {str(e)}")
            
    return parsed_data

# ==========================================
# 2. 阶段二：AI 智能提取 (DeepSeek-V3.2)
# ==========================================

def call_deepseek_api(text, api_key):
    """调用 SiliconFlow API (DeepSeek-V3.2) 进行简历解析"""
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    system_prompt = f"""
    你是一个专业的HR招聘专家助手。你的任务是从简历文本中提取关键信息，并将其转化为标准的JSON格式。
    
    关键指令：
    1. **学校层次识别**：请利用你的知识库，自动识别本科和研究生学校的层次（C9、985、211、重点师范、海外名校等），并填充到 'bachelor_tier' 和 'master_tier' 字段中。
    2. **高中识别**：识别高中是否为著名的重点高中（如各省市第一中学、师大附中等）。
    3. **输出格式**：必须是合法的 JSON 格式，不要包含Markdown标记。
    4. **潜质评分**：根据简历的自我评价、排版质量、职业轨迹进行综合打分（5分制）。
    
    目标 JSON 结构：
    {JSON_SCHEMA}
    """
    
    # 截取文本防止超长 (V3.2 支持较长上下文，这里给 15000 字符足够)
    truncated_text = text[:15000]

    payload = {
        "model": "deepseek-ai/DeepSeek-V3.2", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请分析以下简历内容：\n\n{truncated_text}"}
        ],
        "temperature": 0.1, 
        "response_format": {"type": "json_object"}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        st.error(f"API 调用失败: {str(e)}")
        return None

# ==========================================
# 3. 阶段三：Python 规则评分引擎 (Rule Engine)
# ==========================================

def calculate_score(data):
    """
    基于 AI 提取的 Tag 进行硬性规则打分
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

    # --- 1. 专业匹配 ---
    score_p1 = 0
    comp_str = str(achieve.get('teaching_competition', [])) + str(achieve.get('honor_titles', []))
    if "省" in comp_str and ("一等奖" in comp_str or "前三" in comp_str):
        score_p1 += 5
        logs.append("专业: 省级奖项 +5")
    score += score_p1

    # --- 2. 学习经历 ---
    hs_tier = str(edu.get('high_school_tier', ''))
    if "重点" in hs_tier or "县中" in hs_tier:
        score += 3
        logs.append(f"高中: {hs_tier} +3")
    
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

    abroad = get_num(edu.get('study_abroad_years'))
    if abroad >= 2:
        score += 2
        logs.append("留学: 2年以上 +2")
    
    exchange = str(edu.get('exchange_experience', '否'))
    if exchange == '是':
        score += 1
        logs.append("留学: 交换经历 +1")

    # --- 3. 家庭背景 ---
    gender = str(basic.get('gender', ''))
    marital = str(basic.get('marital_status', ''))
    if gender == '男':
        score += 3
        logs.append("背景: 男性 +3")
    if gender == '女' and '已育' in marital:
        score += 1
        logs.append("背景: 已婚已育 +1")
    
    parents = str(basic.get('parents_background', ''))
    if any(k in parents for k in ['教师', '学校', '机关', '研发', '公务员']):
        score += 1
        logs.append("背景: 父母书香/机关 +1")
        
    residence = str(basic.get('residence', ''))
    if TARGET_CITY in residence:
        score += 1
        logs.append(f"背景: 住{TARGET_CITY} +1")
        
    partner = str(basic.get('partner_location', ''))
    if TARGET_CITY in partner:
        score += 1
        logs.append(f"背景: 配偶在{TARGET_CITY} +1")

    # --- 4. 工作经历 ---
    work_tier = str(work.get('school_tier', ''))
    if "重点" in work_tier or "知名" in work_tier:
        score += 3
        logs.append(f"工作: {work_tier} +3")
        
    non_teaching = get_num(work.get('non_teaching_gap'))
    if non_teaching > 2:
        score -= 3
        logs.append("工作: 非教空窗期 -3")
        
    overseas_work = get_num(work.get('overseas_work_years'))
    if overseas_work >= 1:
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
        score += 1 
        logs.append("能力: 学术成果 +1")

    # --- 6. 管理能力 ---
    mgmt = str(work.get('management_role', ''))
    if mgmt and mgmt not in ['无', '未提及', 'None', 'null']:
        if "年级组长" in mgmt or "教研" in mgmt or "中层" in mgmt:
            score += 3
            logs.append("管理: 中层/组长 +3")
    
    ht_years = get_num(work.get('head_teacher_years'))
    if ht_years >= 5:
        score += 3
        logs.append("管理: 班主任5年+ +3")
    elif ht_years > 0:
        score += 1
        logs.append("管理: 有班主任经历 +1")

    # --- 7 & 8. 个人特质与AI潜质 ---
    potential = get_num(ai.get('potential_score'))
    if potential > 0:
        score += potential
        logs.append(f"AI潜质: +{potential}")

    return score, "; ".join(logs)

# ==========================================
# 4. 主程序界面 (UI)
# ==========================================

def main():
    st.title("🎓 智能简历筛选系统")
    st.caption("Powered by DeepSeek-V3.2 & Streamlit")

    # --- API Key 自动加载 ---
    try:
        api_key = st.secrets["SILICONFLOW_API_KEY"]
    except Exception:
        st.error("❌ 未检测到 API Key。请在 .streamlit/secrets.toml 中配置 SILICONFLOW_API_KEY。")
        st.stop()
            
    # --- 侧边栏 ---
    with st.sidebar:
        st.header("操作面板")
        st.success("✅ API Key 已连接")
        uploaded_files = st.file_uploader(
            "批量上传简历 (PDF/Word)", 
            type=['pdf', 'docx', 'doc'], 
            accept_multiple_files=True
        )
        start_btn = st.button("🚀 开始分析", type="primary", use_container_width=True)

    # --- 主逻辑 ---
    if start_btn and uploaded_files:
        
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        
        status_text.info("📂 正在预处理文件...")
        file_data_list = parse_files(uploaded_files)
        
        for i, file_data in enumerate(file_data_list):
            file_name = file_data['filename']
            content_text = file_data['content']
            
            # 简单校验
            if len(content_text) < 10:
                st.warning(f"⚠️ 文件 {file_name} 内容过短，已跳过。")
                continue

            status_text.text(f"🤖 正在分析 ({i+1}/{total_files}): {file_name}")
            
            # AI 调用
            json_result = call_deepseek_api(content_text, api_key)
            
            if json_result:
                # 规则评分
                total_score, score_logs = calculate_score(json_result)
                
                # 数据提取
                basic = json_result.get('basic_info', {})
                edu = json_result.get('education', {})
                work = json_result.get('work_experience', {})
                ai_eval = json_result.get('ai_assessment', {})
                achieve = json_result.get('achievements', {})
                
                honor_str = ", ".join(achieve.get('honor_titles', [])) if isinstance(achieve.get('honor_titles'), list) else str(achieve.get('honor_titles', ''))
                
                bach_display = f"{edu.get('bachelor_school', '')} ({edu.get('bachelor_tier', '')})"
                mast_display = f"{edu.get('master_school', '')} ({edu.get('master_tier', '')})"
                
                row = {
                    "源文件": file_name,
                    "姓名": basic.get('name'),
                    "性别": basic.get('gender'),
                    "年龄": basic.get('age'),
                    "电话": basic.get('phone'),
                    "学历层次": f"{edu.get('bachelor_tier', '')}/{edu.get('master_tier', '')}",
                    "本科院校": bach_display,
                    "研究生院校": mast_display,
                    "专业": f"{edu.get('bachelor_major', '')}/{edu.get('master_major', '')}",
                    "应聘学科": basic.get('subject'),
                    "预估评分": total_score,
                    "评分明细": score_logs,
                    "教龄": work.get('teaching_years'),
                    "职称/头衔": honor_str,
                    "现单位": f"{work.get('current_company')} ({work.get('school_tier', '')})",
                    "亮点摘要": ai_eval.get('summary'),
                    "风险提示": ai_eval.get('risk_warning'),
                    "AI潜质分": ai_eval.get('potential_score'),
                    "职业轨迹": ai_eval.get('career_trajectory')
                }
                results.append(row)
            else:
                st.error(f"❌ 文件 {file_name} 分析失败")
            
            progress_bar.progress((i + 1) / total_files)
            time.sleep(0.2) 

        status_text.success("✅ 所有文件分析完成！")
        
        # --- 结果展示与导出 ---
        if results:
            df = pd.read_json(json.dumps(results))
            if "预估评分" in df.columns:
                df = df.sort_values(by="预估评分", ascending=False)
            
            st.divider()
            st.subheader(f"📊 分析结果 ({len(results)} 人)")
            
            # 使用 container 限制高度
            with st.container(height=400):
                st.dataframe(
                    df.style.background_gradient(subset=['预估评分'], cmap='Greens'),
                    use_container_width=True
                )
            
            # 生成 Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='面试花名册', index=False)
                workbook = writer.book
                worksheet = writer.sheets['面试花名册']
                # 简单美化
                header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(0, col_num, value, header_fmt)
                worksheet.set_column('A:Z', 18)
                
            st.download_button(
                label="📥 下载 Excel 花名册",
                data=buffer.getvalue(),
                file_name=f"面试花名册_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.ms-excel",
                type="primary"
            )

if __name__ == "__main__":
    main()


