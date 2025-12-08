# ==============================================================================
# 2. 后端功能函数 (修复版：增强容错解析)
# ==============================================================================

@st.cache_data(show_spinner=False)
def ai_parse_excel(df):
    """
    修复版：使用正则提取 JSON 对象，容忍 AI 返回格式错误或连体 JSON
    """
    # 1. 数据预处理：如果数据量太大，限制前 50 行以保证稳定性（可选，根据需求调整）
    # df = df.head(50) 
    
    try:
        csv_content = df.to_csv(index=False)
    except Exception as e:
        return None, f"数据转换CSV失败: {str(e)}"
    
    # 2. System Prompt 强化格式要求
    target_schema = """
    {
        "name": "姓名",
        "age": 30,
        "subject": "学科",
        "edu": 1, 
        "titleLevel": 1,
        "rawTitle": "原始职称"
    }
    """
    
    system_prompt = f"""
    你是一个数据清洗程序。请读取 CSV 数据并转换为 JSON 对象流。
    
    【转换规则】
    1. **必须**为每一行数据生成一个独立的 JSON 对象。
    2. 字段映射：
       - titleLevel: 正高=5, 高级=4, 一级=3, 二级=2, 其他=1
       - edu: 包含"硕/博/研究生"=2, 否则=1
    3. **不要**返回 Markdown 格式，**不要**解释。
    4. 如果某行数据有问题，请跳过该行，不要中断。
    
    【单条数据模版】:
    {target_schema}
    """

    user_prompt = f"请处理以下数据:\n{csv_content}"

    try:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-ai/DeepSeek-V3.2", # 使用 V3.2 甚至 V3
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 8192
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code != 200:
            return None, f"API请求失败: {response.text}"

        response_data = response.json()
        if "choices" not in response_data:
            return None, f"API返回异常: {response_data}"
            
        content = response_data["choices"][0]["message"]["content"]
        
        # ==========================================================
        # 核心修复：使用正则表达式提取所有 JSON 对象
        # ==========================================================
        final_list = []
        
        # 1. 尝试直接标准解析（如果 AI 很听话返回了数组）
        try:
            # 移除可能存在的 markdown 标记
            clean_content = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean_content)
            if isinstance(parsed, list):
                return parsed, None
            if isinstance(parsed, dict):
                 # 处理 {"data": [...]} 的情况
                for v in parsed.values():
                    if isinstance(v, list): return v, None
        except:
            pass # 标准解析失败，进入容错模式
            
        # 2. 容错解析：正则提取每一个 {...} 块
        # 这个正则是非贪婪匹配最外层的 {}，假设 json 内部没有嵌套的大括号结构，
        # 对于扁平的人员数据 {name, age...} 这种正则非常有效且鲁棒。
        import re
        # 查找所有被 {} 包裹的内容
        json_objects = re.findall(r'\{[^{}]+\}', content)
        
        for json_str in json_objects:
            try:
                # 尝试解析每一个单独的对象
                obj = json.loads(json_str)
                # 简单的校验：必须包含 name 或 age 才算有效数据
                if "name" in obj or "subject" in obj:
                    final_list.append(obj)
            except:
                # 如果这个对象解析失败（比如断了一半），跳过它，不影响其他数据
                continue
                
        if not final_list:
            # 兜底：如果还不行，打印片段方便调试
            return None, f"解析失败，未提取到有效数据。AI返回片段:\n{content[:200]}"
            
        return final_list, None

    except Exception as e:
        return None, f"执行异常: {str(e)}"
