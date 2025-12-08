import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import json
import io

# ==============================================================================
# 1. 核心配置与 API 初始化
# ==============================================================================
st.set_page_config(layout="wide", page_title="HKA 师资效能评估 AI版")

# 强制从 Secrets 读取 Key
try:
    API_KEY = st.secrets["SILICONFLOW_API_KEY"]
except Exception:
    st.error("❌ 严重错误：未检测到 SILICONFLOW_API_KEY，系统无法运行。请在 .streamlit/secrets.toml 中配置正确的 Key。")
    st.stop()

# ==============================================================================
# 2. 后端功能函数 (AI 数据清洗)
# ==============================================================================

@st.cache_data(show_spinner=False)
def ai_parse_excel(df):
    """
    使用 DeepSeek-V3.2 清洗任意格式的 Excel/CSV 数据，返回前端标准 JSON List
    """
    # 1. 全量处理 - 严禁截断
    try:
        # 将数据转换为 CSV 字符串，不包含索引
        csv_content = df.to_csv(index=False)
    except Exception as e:
        return None, f"数据转换CSV失败: {str(e)}"
    
    # 2. 定义前端严格需要的数据 Schema
    # 这对应了前端 JS 中的字段: name, age, subject, edu (1/2), titleLevel (1-5), rawTitle
    target_schema = """
    [
      {
        "name": "姓名",
        "age": 30, // 必须为整数。如果缺失，根据职称推测。
        "subject": "学科", // 如 语文, 数学...
        "edu": 1, // 学历量化: 1=本科/专科/其他, 2=研究生/硕士/博士 (如果表头无学历，请智能推断或默认为1)
        "titleLevel": 1, // 职称量化: 1=未定职级, 2=中小学二级, 3=中小学一级, 4=中小学高级, 5=正高级
        "rawTitle": "原始职称字符串"
      }
    ]
    """
    
    # 3. System Prompt - 强化指令，解决表头识别怪异的问题
    system_prompt = f"""
    你是一个专业的人力资源数据清洗专家。你的任务是将用户上传的人员数据清洗为标准的 JSON 格式。

    【表头规范】
    用户数据的表头通常包含以下列：
    姓名, 入职时间, 所在部门, 性别, 年龄, 是否退休, 学科, 职称

    【处理原则 - 绝对严格】
    1. **全量处理**: 必须处理CSV数据中的**每一行**（共 {len(df)} 行），**绝对禁止**只处理前几行或进行摘要。不要偷懒，不要模拟数据，必须基于真实输入。
    2. **真实性**: 严禁编造不存在的人员。
    3. **职称清洗规则 (titleLevel)**:
       - **忽略**职称中的括号内容（如“（特级）”）。
       - "正高级" -> 5
       - "中小学高级" -> 4
       - "中小学一级" -> 3
       - "中小学二级" -> 2
       - "未定职级" 或其他 -> 1
    4. **输出格式**: 必须输出严格的 JSON 数组，不要包含 Markdown 格式（如 ```json ... ```）。请直接返回 JSON 字符串以节省 Token。

    【字段映射】
    - name: 对应 "姓名"
    - age: 对应 "年龄"
    - subject: 对应 "学科"
    - edu: 对应 "学历" 或 "研究生" 列。如果包含"研/硕/博"则为2，否则为1。
    - titleLevel: 按上述规则量化
    - rawTitle: 保留"职称"列的原始文本

    【目标 JSON 结构示例】:
    {target_schema}
    """

    user_prompt = f"这是完整的人员数据（共 {len(df)} 行），请全部清洗并输出 JSON：\n\n{csv_content}"

    # 4. 调用 SiliconFlow API (使用 V3.2)
    try:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-ai/DeepSeek-V3.2", # 已更新为 V3.2
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"}, 
            "temperature": 0.0, # 设为 0 保证数据提取的准确性
            "max_tokens": 8192  # 保持较大 Token 以支持全量输出
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code != 200:
            return None, f"API请求失败 (Code: {response.status_code}): {response.text}"

        response_data = response.json()
        
        if "choices" not in response_data:
            error_msg = response_data.get("error", {}).get("message", str(response_data))
            return None, f"API 返回错误: {error_msg}"
            
        content = response_data["choices"][0]["message"]["content"]
        # 清理可能存在的 Markdown 标记
        content = content.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed_result = json.loads(content)
        except json.JSONDecodeError:
            return None, "AI 返回的数据不是合法的 JSON 格式，请检查源文件是否包含特殊字符。"
        
        final_list = []
        if isinstance(parsed_result, dict):
            # 尝试寻找列表值的 key
            for key, val in parsed_result.items():
                if isinstance(val, list):
                    final_list = val
                    break
        elif isinstance(parsed_result, list):
            final_list = parsed_result
            
        if not final_list:
            return None, "AI 未能从内容中解析出有效的数据列表"
            
        return final_list, None

    except Exception as e:
        return None, f"执行异常: {str(e)}"

# ==============================================================================
# 3. 页面逻辑控制
# ==============================================================================

if 'data_confirmed' not in st.session_state:
    st.session_state.data_confirmed = False
if 'final_json_str' not in st.session_state:
    st.session_state.final_json_str = "null"

def reset_app():
    st.session_state.data_confirmed = False
    st.session_state.final_json_str = "null"
    st.rerun()

# ------------------------------------------------------------------------------
# 页面 A: 数据上传
# ------------------------------------------------------------------------------
if not st.session_state.data_confirmed:
    st.title("🛠️ HKA 师资效能评估 - 智能数据导入")
    
    with st.container():
        st.markdown("""
        ### 👋 欢迎使用
        请上传您的教师花名册文件（支持 Excel 或 CSV）。AI 将自动识别字段并清洗数据。
        
        **支持表头：** 姓名 | 入职时间 | 所在部门 | 性别 | 年龄 | 是否退休 | 学科 | 职称
        """)
        
        uploaded_file = st.file_uploader("📄 点击此处上传文件", type=['xlsx', 'xls', 'csv'])

    if uploaded_file:
        st.divider()
        with st.spinner("🤖 AI 正在全量读取并理解表格结构，这可能需要几十秒，请稍候..."):
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                # --- 移除截断逻辑，全量处理 ---
                # if len(df) > 100: ... (已删除)
                
                ai_result, error_msg = ai_parse_excel(df)
                
                if ai_result and len(ai_result) > 0:
                    st.success(f"✅ 解析成功！共提取 {len(ai_result)} 条数据（全量）。")
                    
                    preview_df = pd.DataFrame(ai_result)
                    st.dataframe(preview_df.head(10), use_container_width=True)
                    st.caption(f"预览前 10 条，实际处理 {len(ai_result)} 条。")
                    
                    if st.button("🚀 确认数据无误，启动大屏", type="primary", use_container_width=True):
                        st.session_state.final_json_str = json.dumps(ai_result, ensure_ascii=False)
                        st.session_state.data_confirmed = True
                        st.rerun()
                else:
                    st.error(f"❌ 数据解析失败: {error_msg}")
            
            except Exception as e:
                st.error(f"处理错误: {str(e)}")

# ------------------------------------------------------------------------------
# 页面 B: 效能评估大屏 (2.5 Pro Version)
# ------------------------------------------------------------------------------
else:
    with st.sidebar:
        st.success("✅ 数据已加载")
        if st.button("🔄 重新上传", use_container_width=True):
            reset_app()

    # HTML 模版：基于你提供的 2.5 Pro 版本，并修改了数据注入逻辑
    html_template = r"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HKA 师资效能评估 2.5 Pro </title>
        
        <!-- Tailwind CSS -->
        <script src="https://cdn.tailwindcss.com"></script>
        <!-- ECharts -->
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <!-- FontAwesome -->
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
            
            body { font-family: 'Noto Sans SC', sans-serif; background-color: #f8fafc; color: #334155; }
            
            /* --- Components --- */
            .card {
                background: white;
                border-radius: 12px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
                border: 1px solid #e2e8f0;
                transition: box-shadow 0.2s;
            }
            .card:hover { box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }

            /* Sliders */
            input[type=range] { -webkit-appearance: none; background: transparent; width: 100%; cursor: pointer; }
            input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; height: 14px; width: 14px; border-radius: 50%; background: #3b82f6; margin-top: -5px; box-shadow: 0 1px 2px rgba(0,0,0,0.2); border: 2px solid white; }
            input[type=range]::-webkit-slider-runnable-track { width: 100%; height: 4px; background: #cbd5e1; border-radius: 2px; }
            input[type=range].accent-emerald-600::-webkit-slider-thumb { background: #059669; }
            input[type=range].accent-purple-600::-webkit-slider-thumb { background: #7c3aed; }
            
            .input-label { font-size: 0.7rem; font-weight: 600; color: #64748b; text-transform: uppercase; display: flex; justify-content: space-between; margin-bottom: 2px; }
            
            /* Tabs & Buttons */
            .preset-btn { font-size: 0.7rem; padding: 4px 8px; border-radius: 4px; border: 1px solid #e2e8f0; background: #f8fafc; color: #475569; transition: all 0.15s; }
            .preset-btn:hover { background: #e2e8f0; color: #1e293b; border-color: #cbd5e1; }
            .preset-btn.active { background: #dbeafe; color: #2563eb; border-color: #bfdbfe; font-weight: 600; }

            .tab-btn { padding: 8px; font-size: 0.75rem; font-weight: 600; border-radius: 6px; cursor: pointer; flex: 1; text-align: center; transition: all 0.2s; }
            .tab-active { background-color: #eff6ff; color: #2563eb; box-shadow: inset 0 0 0 1px #bfdbfe; }
            .tab-inactive { background-color: transparent; color: #64748b; }
            .tab-inactive:hover { background-color: #f1f5f9; }

            /* Scrollbars */
            .custom-scroll::-webkit-scrollbar { width: 4px; }
            .custom-scroll::-webkit-scrollbar-track { background: transparent; }
            .custom-scroll::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 10px; }

            /* Chat Widget */
            #chat-wrapper { position: fixed; bottom: 24px; right: 24px; z-index: 50; display: flex; flex-direction: column; align-items: flex-end; }
            #chat-window { width: 360px; height: 480px; background: white; border-radius: 12px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1); border: 1px solid #e2e8f0; display: none; flex-direction: column; overflow: hidden; margin-bottom: 16px; animation: slideUp 0.2s ease-out; }
            @keyframes slideUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            
            .chat-bubble { max-width: 88%; padding: 10px 14px; border-radius: 12px; font-size: 0.85rem; line-height: 1.5; margin-bottom: 10px; word-wrap: break-word; }
            .chat-bubble.user { background: #3b82f6; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
            .chat-bubble.ai { background: #f1f5f9; color: #334155; align-self: flex-start; border-bottom-left-radius: 2px; border: 1px solid #e2e8f0; }

            .fab-btn { width: 50px; height: 50px; background: #3b82f6; border-radius: 50%; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); display: flex; align-items: center; justify-content: center; color: white; font-size: 20px; cursor: pointer; transition: transform 0.2s; }
            .fab-btn:hover { transform: scale(1.05); background: #2563eb; }

            /* AI Output Styles */
            .ai-report-section { margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0; }
            .ai-report-section:last-child { border-bottom: none; }
            .ai-label { font-weight: 700; color: #475569; font-size: 0.8rem; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
            .ai-text { font-size: 0.85rem; color: #334155; line-height: 1.6; text-align: justify; }

            /* Reasoning Box Styles (Report) */
            .reasoning-container {
                background: #f8fafc;
                border-left: 3px solid #8b5cf6;
                border-radius: 4px;
                padding: 10px;
                margin-bottom: 12px;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                font-size: 0.75rem;
                color: #64748b;
                line-height: 1.5;
                max-height: 180px;
                overflow-y: auto;
                display: none;
            }
            .reasoning-title {
                font-weight: 700; color: #7c3aed; margin-bottom: 4px; display: flex; align-items: center; gap: 4px;
                font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em;
            }
            .reasoning-content { white-space: pre-wrap; }
            .thinking-dot { display: inline-block; width: 4px; height: 4px; background: #8b5cf6; border-radius: 50%; animation: pulse 1s infinite; }

            /* Chat Bubble Reasoning details */
            details.chat-reasoning {
                margin-bottom: 8px;
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 4px 8px;
            }
            details.chat-reasoning summary {
                font-size: 0.7rem; color: #8b5cf6; font-weight: 600; cursor: pointer; outline: none;
                list-style: none; display: flex; align-items: center; gap: 4px;
            }
            details.chat-reasoning summary::-webkit-details-marker { display: none; }
            details.chat-reasoning summary::before {
                content: '💡'; font-size: 0.8rem;
            }
            .chat-reasoning-text {
                margin-top: 4px;
                font-size: 0.7rem;
                color: #64748b;
                border-top: 1px dashed #e2e8f0;
                padding-top: 4px;
                white-space: pre-wrap;
                font-family: monospace;
            }

            /* Tooltip for TQI - Light Theme */
            .tooltip-trigger:hover .tooltip-content { display: block; opacity: 1; transform: translateY(0); }
            .tooltip-content { 
                display: none; opacity: 0; transition: all 0.2s; 
                position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
                background: white; color: #334155; padding: 16px; border-radius: 8px; border: 1px solid #e2e8f0;
                margin-top: 8px; font-size: 0.75rem; line-height: 1.6; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15);
                transform: translateY(-5px); pointer-events: none;
            }
            
            /* Toggle Switch for Chat R1 - Keeping style but forcing R1 */
            .toggle-checkbox:checked {
                right: 0;
                border-color: #8b5cf6;
            }
            .toggle-checkbox:checked + .toggle-label {
                background-color: #8b5cf6;
            }
            .toggle-checkbox:checked + .toggle-label:before {
                transform: translateX(100%);
            }
        </style>
    </head>
    <body class="h-screen flex flex-col overflow-hidden">

        <!-- Header -->
        <nav class="bg-white border-b border-slate-200 h-14 shrink-0 flex items-center px-6 justify-between z-40 shadow-sm">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 bg-indigo-600 rounded flex items-center justify-center text-white shadow-sm">
                    <i class="fa-solid fa-layer-group text-sm"></i>
                </div>
                <!-- 替换 R1 为 AI -->
                <h1 class="font-bold text-slate-700 tracking-tight">HKA 师资效能评估 <span class="text-xs font-normal text-slate-400 ml-1">2.5 Pro (AI Edition)</span></h1>
            </div>
            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded border border-emerald-100">
                    <span class="relative flex h-2 w-2">
                      <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <!-- 替换 SiliconFlow R1 为 SiliconFlow AI -->
                    SiliconFlow AI
                </div>
                <button onclick="resetAll()" class="text-xs text-slate-500 hover:text-slate-700 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded transition">重置沙盘</button>
            </div>
        </nav>

        <!-- Main Grid -->
        <main class="flex-1 grid grid-cols-12 gap-4 p-4 min-h-0 max-w-[1920px] mx-auto w-full">

            <!-- LEFT: Configuration -->
            <div class="col-span-3 flex flex-col gap-4 custom-scroll overflow-y-auto pr-1 pb-10">
                
                <!-- Simulation Controller -->
                <div class="card p-4 flex flex-col gap-4 border-t-4 border-t-emerald-500">
                    <div class="flex justify-between items-center border-b border-slate-100 pb-2">
                        <h2 class="text-sm font-bold text-slate-700 flex items-center gap-2">
                            <i class="fa-solid fa-sliders text-emerald-500"></i> 模拟招聘
                        </h2>
                        <div class="flex bg-slate-100 rounded-lg p-0.5">
                            <div id="mode-a" class="tab-btn tab-active" onclick="setMode('A')">专家模式</div>
                            <div id="mode-b" class="tab-btn tab-inactive" onclick="setMode('B')">简易模式</div>
                        </div>
                    </div>

                    <!-- Plan A: Expert -->
                    <div id="panel-a" class="flex flex-col gap-4">
                        <!-- Quick Presets -->
                        <div class="grid grid-cols-3 gap-2">
                            <button class="preset-btn" onclick="applyPreset('youth')">🌱 青年生力军</button>
                            <button class="preset-btn" onclick="applyPreset('middle')">🦴 骨干填充</button>
                            <button class="preset-btn" onclick="applyPreset('expert')">👑 高端引进</button>
                        </div>

                        <div>
                            <div class="input-label"><span>招聘总人数</span> <span id="val-a-count" class="text-emerald-600">0</span></div>
                            <input type="range" id="in-a-count" min="0" max="60" value="0" class="accent-emerald-600">
                        </div>

                        <div class="bg-slate-50 rounded p-3 border border-slate-200 flex flex-col gap-3">
                            <div class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">年龄分布控制</div>
                            <div>
                                <div class="flex justify-between text-[10px] text-slate-500 mb-1"><span>22-29岁 (教坛新秀)</span> <span id="val-a-20s">40%</span></div>
                                <input type="range" id="in-a-20s" min="0" max="100" value="40">
                            </div>
                            <div>
                                <div class="flex justify-between text-[10px] text-slate-500 mb-1"><span>30-39岁 (核心骨干)</span> <span id="val-a-30s">40%</span></div>
                                <input type="range" id="in-a-30s" min="0" max="100" value="40">
                            </div>
                            <div>
                                <div class="flex justify-between text-[10px] text-slate-500 mb-1"><span>40-49岁 (经验专家)</span> <span id="val-a-40s">10%</span></div>
                                <input type="range" id="in-a-40s" min="0" max="100" value="10">
                            </div>
                            <div>
                                <div class="flex justify-between text-[10px] text-slate-500 mb-1"><span>50+岁 (资深/特聘)</span> <span id="val-a-50s">10%</span></div>
                                <input type="range" id="in-a-50s" min="0" max="100" value="10">
                            </div>
                        </div>

                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <div class="input-label"><span>硕士及以上率</span> <span id="val-a-master">50%</span></div>
                                <input type="range" id="in-a-master" min="0" max="100" value="50">
                            </div>
                            <div>
                                <div class="input-label"><span>高级职称潜力</span> <span id="val-a-senior">20%</span></div>
                                <input type="range" id="in-a-senior" min="0" max="100" value="20">
                            </div>
                        </div>
                        <div class="text-[10px] text-slate-400 leading-tight">
                            <i class="fa-solid fa-circle-info mr-1"></i> 注意：生成时将强制执行现实年龄约束（如36岁以下不可生成高级职称）。
                        </div>
                    </div>

                    <!-- Plan B: Simple -->
                    <div id="panel-b" class="hidden flex flex-col gap-4">
                        <div class="p-3 bg-blue-50 text-blue-700 text-xs rounded border border-blue-100 leading-relaxed">
                            自动化模式：系统将随机生成22-30岁的青年教师填补空缺，学科分布参照当前比例。
                        </div>
                        <div>
                            <div class="input-label"><span>招聘人数</span> <span id="val-b-count" class="text-blue-600">0</span></div>
                            <input type="range" id="in-b-count" min="0" max="50" value="0" class="accent-blue-600">
                        </div>
                        <div>
                            <div class="input-label"><span>硕士人数</span> <span id="val-b-master" class="text-purple-600">0</span></div>
                            <input type="range" id="in-b-master" min="0" max="50" value="0" class="accent-purple-600">
                        </div>
                    </div>
                </div>

                <!-- Ideal Model Config -->
                <div class="card p-4 flex flex-col gap-3 border-l-4 border-l-blue-500">
                    <div class="flex justify-between items-center border-b border-slate-100 pb-2 mb-1">
                        <h2 class="text-sm font-bold text-slate-700"><i class="fa-solid fa-bullseye text-blue-500 mr-1"></i> 理想模型参数</h2>
                    </div>
                    <div>
                        <div class="input-label"><span>最佳平均年龄</span> <span id="disp-opt-age" class="text-blue-600">32岁</span></div>
                        <input type="range" id="opt-age" min="28" max="45" value="32">
                    </div>
                    <div>
                        <div class="input-label"><span>目标硕士率</span> <span id="disp-opt-edu" class="text-purple-600">50%</span></div>
                        <input type="range" id="opt-edu" min="10" max="100" value="50">
                    </div>
                    <div>
                        <div class="input-label"><span>职称重要性</span> <span id="disp-opt-title" class="text-orange-600">30%</span></div>
                        <input type="range" id="opt-title" min="5" max="60" value="30">
                    </div>
                    <!-- Standard Deviation Moved Here -->
                    <div>
                        <div class="input-label"><span>最佳标准差</span> <span id="disp-opt-sigma" class="text-slate-500">7</span></div>
                        <input type="range" id="opt-sigma" min="3" max="12" value="7" step="0.5">
                    </div>
                </div>

                 <!-- Weights -->
                 <div class="card p-4 flex flex-col gap-2">
                    <div class="flex justify-between items-center">
                        <h2 class="text-xs font-bold text-slate-500 uppercase">TQI 权重分配</h2>
                        <span id="weight-alert" class="text-[10px] text-orange-500"></span>
                    </div>
                    <div class="flex items-center gap-2 text-[10px]">
                        <span class="w-8 text-right">结构</span>
                        <input type="range" id="w-age" max="100" value="40" class="h-1">
                        <span id="v-w-age" class="w-6">40</span>
                    </div>
                    <div class="flex items-center gap-2 text-[10px]">
                        <span class="w-8 text-right">学历</span>
                        <input type="range" id="w-edu" max="100" value="30" class="h-1">
                        <span id="v-w-edu" class="w-6">30</span>
                    </div>
                    <div class="flex items-center gap-2 text-[10px]">
                        <span class="w-8 text-right">职称</span>
                        <input type="range" id="w-title" max="100" value="30" class="h-1">
                        <span id="v-w-title" class="w-6">30</span>
                    </div>
                </div>

                <!-- Guide Section (Light Theme) -->
                <div class="card p-4 bg-slate-50 text-slate-600 text-[10px] leading-relaxed border border-slate-200">
                    <h3 class="text-slate-700 font-bold mb-3 border-b border-slate-200 pb-2 flex items-center gap-2"><i class="fa-solid fa-book-open text-emerald-500"></i> 算法与逻辑说明</h3>
                    
                    <div class="mb-3">
                        <strong class="text-emerald-600 block mb-1">1. 结构得分 (Structure Score)</strong>
                        <p class="opacity-90 text-justify mb-1"><strong>思想：</strong>拒绝“平均值陷阱”。我们追求符合正态分布的“生态梯队”。</p>
                        <p class="opacity-90 text-justify"><strong>计算：</strong>采用正态分布公式拟合。以最佳年龄为峰值，理想标准差为基准，计算现状分布与理想曲线的重合度。</p>
                    </div>

                    <div class="mb-3">
                        <strong class="text-purple-600 block mb-1">2. 边际递减 (Diminishing Returns)</strong>
                        <p class="opacity-90 text-justify"><strong>思想：</strong>资源配置最优化。在达到“理想目标值”前，得分快速增长；超过后增长放缓，反对盲目内卷。</p>
                    </div>

                    <div class="mb-3">
                        <strong class="text-blue-600 block mb-1">3. 多维效能 (Radar Chart)</strong>
                        <ul class="list-disc pl-3 opacity-90 space-y-1">
                            <li><strong>结构健康：</strong>标准差在 6-8 之间为健康。</li>
                            <li><strong>职称达标：</strong>高职称占比相对于目标的完成率。</li>
                        </ul>
                    </div>

                    <!-- Added Constraint Info -->
                    <div>
                        <strong class="text-orange-600 block mb-1">4. 现实约束 (Logic Gate)</strong>
                        <p class="opacity-90 text-justify text-[9px]">
                            <i class="fa-solid fa-shield-halved mr-1"></i>模拟系统内置了严格的职称-年龄门限，防止生成不合逻辑的数据：
                            <br>• 26岁以下：按分布生成 (一级30% / 二级40% / 未定30%)
                            <br>• <span class="text-indigo-600 font-bold">特例：26岁以下一级教师中，80%强制设定为研究生</span>
                            <br>• 36岁以下：最高一级
                            <br>• 36岁以上：开放高级职称
                            <br>• 正高级：仅限50岁以上或特聘
                        </p>
                    </div>
                </div>
            </div>

            <!-- CENTER: Charts - NO SCROLL -->
            <div class="col-span-5 flex flex-col gap-4 h-full overflow-hidden">
                
                <!-- TQI Horizontal Card -->
                <div class="card px-5 py-3 h-24 flex items-center gap-5 relative shrink-0 tooltip-trigger cursor-help z-20 overflow-visible">
                    <div class="absolute left-0 top-0 bottom-0 w-1.5 bg-indigo-500 rounded-l-lg"></div>
                    
                    <!-- Left: Text -->
                    <div class="flex flex-col min-w-[100px]">
                        <div class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-0.5">TQI 指数 <i class="fa-regular fa-circle-question ml-1 text-slate-300"></i></div>
                        <div class="flex items-baseline gap-1">
                            <div id="tqi-score" class="text-4xl font-black text-slate-800 tracking-tighter leading-none">--</div>
                            <span class="text-xs font-bold text-slate-400">/100</span>
                        </div>
                    </div>

                    <!-- Right: Bar -->
                    <div class="flex-1 flex flex-col gap-2 pt-1">
                        <div class="flex justify-between text-[10px] text-slate-500 font-medium">
                            <span>综合效能评级</span>
                            <span id="tqi-grade" class="text-indigo-600">Calculating...</span>
                        </div>
                        <div class="h-3 w-full bg-slate-100 rounded-full overflow-hidden">
                            <div id="tqi-bar" class="h-full bg-gradient-to-r from-indigo-400 to-indigo-600 rounded-full shadow-sm transition-all duration-700" style="width: 0%"></div>
                        </div>
                    </div>

                    <!-- Tooltip Content (Dynamic) - Light Theme -->
                    <div class="tooltip-content w-[320px]" id="tqi-tooltip-content">
                        <!-- Content injected by JS -->
                    </div>
                </div>

                <!-- Histogram (Header Legend) -->
                <div class="card p-4 h-[300px] flex flex-col shrink-0">
                    <div class="flex justify-between items-center mb-1 border-b border-slate-50 pb-2">
                        <h3 class="text-sm font-bold text-slate-700">年龄结构分布</h3>
                        <!-- Legend moved here -->
                        <div class="flex items-center gap-3 text-[10px]">
                             <div class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-blue-500"></span>现有</div>
                             <div class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-emerald-500"></span>模拟</div>
                             <div class="flex items-center gap-1"><span class="w-3 h-0.5 border-t border-dashed border-amber-500"></span>理想</div>
                             <div class="h-3 w-[1px] bg-slate-200 mx-1"></div>
                             <select id="subject-filter" class="text-xs bg-transparent outline-none text-slate-500 hover:text-blue-600 cursor-pointer font-medium"><option value="all">全校总览</option></select>
                        </div>
                    </div>
                    <div id="chart-hist" class="flex-1 -ml-2"></div>
                </div>

                <!-- Scatter Matrix -->
                <div class="card p-4 h-[320px] flex flex-col shrink-0">
                    <div class="flex justify-between items-center mb-2 border-b border-slate-50 pb-2">
                        <h3 class="text-sm font-bold text-slate-700">职称-年龄散点图</h3>
                        <!-- Added Scatter Selector -->
                        <div class="flex items-center gap-3 text-[10px]">
                            <div class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500"></span>现有</div>
                            <div class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-500"></span>模拟</div>
                            <div class="h-3 w-[1px] bg-slate-200 mx-1"></div>
                            <select id="subject-filter-scatter" class="text-xs bg-transparent outline-none text-slate-500 hover:text-blue-600 cursor-pointer font-medium"><option value="all">全校总览</option></select>
                       </div>
                    </div>
                    <div id="chart-scatter" class="flex-1"></div>
                </div>
            </div>

            <!-- RIGHT: AI Analysis -->
            <div class="col-span-4 flex flex-col gap-4 h-full overflow-hidden pb-4">
                <!-- Radar -->
                <div class="card p-4 h-[220px] flex flex-col shrink-0">
                    <h3 class="text-xs font-bold text-slate-500 uppercase mb-2">多维效能对比</h3>
                    <div id="chart-radar" class="flex-1"></div>
                </div>

                <!-- AI Report -->
                <div class="card flex-1 flex flex-col bg-white relative overflow-hidden border-t-4 border-t-purple-500">
                    <div class="p-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
                        <div class="flex items-center gap-2">
                            <i class="fa-solid fa-robot text-purple-600"></i>
                            <span class="font-bold text-slate-700 text-sm">智能诊断报告</span>
                        </div>
                        <div class="flex gap-2">
                            <!-- Buttons Updated -->
                            <button onclick="runAI()" id="btn-ai" class="text-xs bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 px-3 py-1.5 rounded shadow-sm transition flex items-center gap-1">
                                <i class="fa-solid fa-wand-magic-sparkles text-blue-500"></i> AI 诊断
                            </button>
                            <button onclick="runDeepReasoning()" id="btn-reason" class="text-xs bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded shadow transition flex items-center gap-1">
                                <i class="fa-solid fa-brain"></i> 深度思考
                            </button>
                        </div>
                    </div>
                    <div id="ai-content" class="p-5 overflow-y-auto custom-scroll flex-1 text-sm bg-white">
                        <div class="h-full flex flex-col items-center justify-center text-slate-400 gap-3">
                            <div class="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center">
                                <i class="fa-solid fa-microchip text-xl opacity-30"></i>
                            </div>
                            <p class="text-xs">选择模式并生成诊断</p>
                        </div>
                    </div>
                </div>
            </div>

        </main>

        <!-- Floating Chat -->
        <div id="chat-wrapper">
            <div id="chat-window">
                <div class="bg-slate-800 text-white p-3 flex justify-between items-center cursor-default">
                    <span class="text-xs font-bold"><i class="fa-solid fa-comment-dots mr-1"></i> 效能助手</span>
                    <button onclick="toggleChat()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-times"></i></button>
                </div>
                <div id="chat-body" class="flex-1 bg-slate-50 p-4 overflow-y-auto custom-scroll flex flex-col">
                    <div class="chat-bubble ai">你好！我是你的数据助手。有什么我可以帮你的？</div>
                </div>
                <div class="p-3 bg-white border-t border-slate-200 flex flex-col gap-2">
                    <div class="flex items-center justify-between text-xs text-slate-500 px-1">
                        <span>深度思考 (AI) - 已全局启用</span>
                        <label class="relative inline-flex items-center cursor-pointer">
                          <input type="checkbox" id="chat-mode-toggle" class="sr-only peer" checked disabled>
                          <div class="w-8 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[0px] after:left-[0px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
                        </label>
                    </div>
                    <div class="flex gap-2">
                        <input type="text" id="chat-input" class="flex-1 bg-slate-100 border-none rounded px-3 py-1.5 text-sm focus:ring-1 focus:ring-blue-500 outline-none" placeholder="输入问题...">
                        <button onclick="sendChat()" class="bg-blue-600 text-white rounded px-3 py-1.5 text-sm hover:bg-blue-700"><i class="fa-solid fa-paper-plane"></i></button>
                    </div>
                </div>
            </div>
            <div class="fab-btn" onclick="toggleChat()">
                <i class="fa-solid fa-message"></i>
            </div>
        </div>

        <script>
            // =========================================
            // 1. Configuration & Consts
            // =========================================
            const DEEPSEEK_KEY = "[[SILICONFLOW_KEY]]";
            // SiliconFlow API Endpoint (Standard V3)
            const API_URL = "https://api.siliconflow.cn/v1/chat/completions";

            // Title Mapping
            const LEVEL_NAMES = { 1:'未定职级', 2:'中小学二级', 3:'中小学一级', 4:'中小学高级', 5:'正高级' };

            // Realistic Age Constraints for SIMULATION (Logic Gate)
            const AGE_CONSTRAINTS = [
                { maxAge: 24, maxLevel: 1 }, 
                { maxAge: 29, maxLevel: 2 }, 
                { maxAge: 39, maxLevel: 3 }, 
                { maxAge: 49, maxLevel: 4 }, 
                { maxAge: 99, maxLevel: 5 }  
            ];

            let state = {
                simMode: 'A',
                a: { count: 0, dist: [40,40,10,10], master: 50, senior: 20 },
                b: { count: 0, master: 0 },
                opt: { age: 32, edu: 50, title: 30, sigma: 7 },
                weights: { age: 40, edu: 30, title: 30 },
                filter: 'all'
            };

            // =========================================
            // 2. Data Handling (Updated: Use Injected JSON)
            // =========================================
            // 这里我们直接注入 Python 清洗好的 JSON 数据，而不是在前端解析 Raw CSV
            // 这确保了 "AI 清洗" 的价值被保留，同时使用了新的 UI
            const injectedData = [[DATA_INSERT]];
            let baseData = [];

            // =========================================
            // 3. Simulation Engine
            // =========================================
            function getSimulatedData() {
                let simData = [];
                // 确保至少有学科数据，防止空数组报错
                const subjects = baseData.length > 0 ? [...new Set(baseData.map(d=>d.subject))] : ['通用'];
                const getRandomSub = () => subjects[Math.floor(Math.random()*subjects.length)];

                // UPDATED: Valid Title Generation logic
                const getValidTitle = (age, preferredSeniority) => {
                    if (age < 26) {
                        const rand = Math.random();
                        if (rand < 0.3) return 3; 
                        if (rand < 0.7) return 2; 
                        return 1;                
                    }
                    if (age < 36) return (Math.random() < 0.5 + (preferredSeniority * 0.5)) ? 3 : 2;
                    if (age < 50) return (Math.random() < preferredSeniority) ? 4 : 3;
                    if (Math.random() < preferredSeniority * 0.3) return 5;
                    if (Math.random() < preferredSeniority) return 4;
                    return 3;
                };

                if (state.simMode === 'A' && state.a.count > 0) {
                    const count = state.a.count;
                    const [p20, p30, p40, p50] = state.a.dist;
                    const totalW = p20+p30+p40+p50;
                    
                    const counts = [
                        Math.round(count * (p20/totalW)),
                        Math.round(count * (p30/totalW)),
                        Math.round(count * (p40/totalW))
                    ];
                    counts.push(count - counts.reduce((a,b)=>a+b,0)); 

                    const ranges = [[22,29], [30,39], [40,49], [50,59]];
                    
                    ranges.forEach((range, idx) => {
                        for(let i=0; i<counts[idx]; i++) {
                            const age = Math.floor(Math.random() * (range[1] - range[0] + 1)) + range[0];
                            const level = getValidTitle(age, state.a.senior / 100);
                            
                            let edu = 1;
                            if (age < 26 && level === 3) {
                                edu = Math.random() < 0.8 ? 2 : 1;
                            } else {
                                edu = Math.random() < (state.a.master/100) ? 2 : 1;
                            }

                            simData.push({
                                name: `模拟A`,
                                age: age,
                                subject: getRandomSub(),
                                edu: edu,
                                titleLevel: level,
                                isSim: true
                            });
                        }
                    });

                } else if (state.simMode === 'B' && state.b.count > 0) {
                    for(let i=0; i<state.b.count; i++) {
                        const age = Math.floor(Math.random() * 8) + 22; 
                        simData.push({
                            name: `模拟B`,
                            age: age,
                            subject: getRandomSub(),
                            edu: i < state.b.master ? 2 : 1,
                            titleLevel: getValidTitle(age, 0),
                            isSim: true
                        });
                    }
                }
                return simData;
            }

            // =========================================
            // 4. TQI Algorithm
            // =========================================
            function calculateGaussianScore(val, target, sigma=5) {
                const diff = val - target;
                const score = Math.exp(- (diff*diff) / (2*sigma*sigma));
                return score * 100;
            }

            function calcMetrics(datasetOverride = null) {
                const sim = getSimulatedData();
                const all = datasetOverride || [...baseData, ...sim];
                let filtered = state.filter === 'all' ? all : all.filter(d => d.subject === state.filter);
                
                if (filtered.length === 0) return {
                    data: [], simCount: 0, 
                    metrics: { avgAge:0, masterRate:0, seniorRate:0, ageStdDev:0, count: 0 },
                    scores: { sAge:0, sEdu:0, sTitle:0, final: "0.0" }
                };

                const totalAge = filtered.reduce((a,b)=>a+b.age,0);
                const avgAge = totalAge / filtered.length;

                // Structure Score
                const ageVariance = filtered.reduce((a,b) => a + Math.pow(b.age - avgAge, 2), 0) / filtered.length;
                const ageStdDev = Math.sqrt(ageVariance);
                const stdDevScore = calculateGaussianScore(ageStdDev, state.opt.sigma, 2.5);
                
                const meanScore = calculateGaussianScore(avgAge, state.opt.age, 4);
                const sAge = (meanScore * 0.7) + (stdDevScore * 0.3);

                // Edu Score
                const masterCount = filtered.filter(d => d.edu===2).length;
                const masterRate = (masterCount / filtered.length) * 100;
                let sEdu = masterRate >= state.opt.edu ? 
                    100 + (masterRate - state.opt.edu) * 0.2 : 
                    (masterRate / state.opt.edu) * 100; 

                // Title Score
                const seniorCount = filtered.filter(d => d.titleLevel >= 4).length; 
                const seniorRate = (seniorCount / filtered.length) * 100;
                let sTitle = seniorRate >= state.opt.title ?
                    100 : (seniorRate / state.opt.title) * 100;

                const wTotal = parseInt(state.weights.age) + parseInt(state.weights.edu) + parseInt(state.weights.title);
                const final = ((sAge * state.weights.age) + (sEdu * state.weights.edu) + (sTitle * state.weights.title)) / wTotal;

                return {
                    data: all,
                    simCount: all.filter(d => d.isSim).length,
                    metrics: { avgAge, masterRate, seniorRate, ageStdDev, count: filtered.length },
                    scores: { sAge, sEdu, sTitle, final: final.toFixed(1) }
                };
            }

            // =========================================
            // 5. UI & Charts
            // =========================================
            let charts = {};

            function init() {
                // 使用 Python 注入的数据
                if (injectedData && Array.isArray(injectedData)) {
                    baseData = injectedData;
                } else {
                    baseData = [];
                }
                
                // Populate Subject Filter
                const subjs = [...new Set(baseData.map(d=>d.subject))].filter(Boolean).sort();
                
                const selHist = document.getElementById('subject-filter');
                const selScatter = document.getElementById('subject-filter-scatter');
                
                subjs.forEach(s => {
                    selHist.appendChild(new Option(s, s));
                    selScatter.appendChild(new Option(s, s));
                });

                const syncFilter = (val) => {
                    state.filter = val;
                    selHist.value = val;
                    selScatter.value = val;
                    update();
                };

                selHist.addEventListener('change', (e) => syncFilter(e.target.value));
                selScatter.addEventListener('change', (e) => syncFilter(e.target.value));

                charts.hist = echarts.init(document.getElementById('chart-hist'));
                charts.scatter = echarts.init(document.getElementById('chart-scatter'));
                charts.radar = echarts.init(document.getElementById('chart-radar'));

                // Bind Inputs
                bindInput('in-a-count', (v) => { state.a.count = parseInt(v); document.getElementById('val-a-count').innerText = v; });
                bindInput('in-a-20s', (v) => state.a.dist[0] = parseInt(v), 'val-a-20s');
                bindInput('in-a-30s', (v) => state.a.dist[1] = parseInt(v), 'val-a-30s');
                bindInput('in-a-40s', (v) => state.a.dist[2] = parseInt(v), 'val-a-40s');
                bindInput('in-a-50s', (v) => state.a.dist[3] = parseInt(v), 'val-a-50s');
                bindInput('in-a-master', (v) => state.a.master = parseInt(v), 'val-a-master');
                bindInput('in-a-senior', (v) => state.a.senior = parseInt(v), 'val-a-senior');
                
                bindInput('in-b-count', (v) => state.b.count = parseInt(v), 'val-b-count');
                bindInput('in-b-master', (v) => state.b.master = parseInt(v), 'val-b-master');

                bindInput('opt-age', (v) => state.opt.age = parseInt(v), 'disp-opt-age');
                bindInput('opt-edu', (v) => state.opt.edu = parseInt(v), 'disp-opt-edu');
                bindInput('opt-title', (v) => state.opt.title = parseInt(v), 'disp-opt-title');
                bindInput('opt-sigma', (v) => state.opt.sigma = parseFloat(v), 'disp-opt-sigma');

                bindInput('w-age', (v) => state.weights.age = parseInt(v), 'v-w-age');
                bindInput('w-edu', (v) => state.weights.edu = parseInt(v), 'v-w-edu');
                bindInput('w-title', (v) => state.weights.title = parseInt(v), 'v-w-title');

                document.getElementById('chat-input').addEventListener('keypress', (e) => {
                    if(e.key === 'Enter') sendChat();
                });

                window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()));
                update();
            }

            function bindInput(id, callback, dispId) {
                const el = document.getElementById(id);
                el.addEventListener('input', (e) => {
                    const v = e.target.value;
                    if(dispId) document.getElementById(dispId).innerText = v + ((id.includes('age') || id.includes('sigma')) ? '' : '%');
                    callback(v);
                    update();
                });
            }

            function update() {
                const res = calcMetrics();
                if(!res) return;
                
                const { metrics, scores, data } = res;
                
                // 1. TQI Bar
                const score = parseFloat(scores.final);
                document.getElementById('tqi-score').innerText = score;
                document.getElementById('tqi-bar').style.width = score + '%';
                
                let grade = 'C-';
                if(score > 90) grade = 'S (卓越)';
                else if(score > 80) grade = 'A (优秀)';
                else if(score > 70) grade = 'B (良好)';
                else if(score > 60) grade = 'C (合格)';
                document.getElementById('tqi-grade').innerText = grade;

                // Update Tooltip
                const totalW = parseInt(state.weights.age) + parseInt(state.weights.edu) + parseInt(state.weights.title);
                document.getElementById('tqi-tooltip-content').innerHTML = `
                    <div class="font-bold text-emerald-600 mb-2 pb-1 border-b border-slate-200">TQI 计算公式</div>
                    <div class="font-mono text-xs text-blue-600 mb-2 break-all">
                        (结构分×<span class="font-bold">${state.weights.age}</span> + 学历分×<span class="font-bold">${state.weights.edu}</span> + 职称分×<span class="font-bold">${state.weights.title}</span>) / <span class="font-bold">${totalW}</span>
                    </div>
                `;

                // 2. Histogram
                let filtered = state.filter === 'all' ? data : data.filter(d => d.subject === state.filter);
                const xData = [];
                const yExist = [];
                const ySim = [];
                const yIdeal = [];
                
                for(let i=20; i<=60; i+=5) {
                    xData.push(i);
                    const existC = filtered.filter(d => !d.isSim && d.age >= i && d.age < i+5).length;
                    const simC = filtered.filter(d => d.isSim && d.age >= i && d.age < i+5).length;
                    yExist.push(existC);
                    ySim.push(simC);
                    
                    const total = filtered.length;
                    const center = i + 2.5;
                    const g = Math.exp(-Math.pow(center - state.opt.age, 2) / (2 * (state.opt.sigma * state.opt.sigma))); 
                    yIdeal.push( (g * total * 0.4).toFixed(1) ); 
                }

                charts.hist.setOption({
                    tooltip: { trigger: 'axis' },
                    legend: { show: false }, 
                    grid: { top: 20, bottom: 20, left: 30, right: 10 },
                    xAxis: { type: 'category', data: xData.map(x=>`${x}-${x+4}`), axisLabel: { fontSize: 10 } },
                    yAxis: { type: 'value', splitLine: { show: false } },
                    series: [
                        { name: '现有', type: 'bar', stack: 't', data: yExist, itemStyle: { color: '#3b82f6' }, barWidth: '60%' },
                        { name: '模拟', type: 'bar', stack: 't', data: ySim, itemStyle: { color: '#10b981' } },
                        { name: '理想曲线', type: 'line', data: yIdeal, smooth: true, showSymbol: false, lineStyle: { type: 'dashed', color: '#f59e0b' } }
                    ]
                });

                // 3. Scatter
                const scatterData = filtered.map(d => {
                    return {
                        value: [d.age, d.titleLevel + (Math.random()*0.4 - 0.2)],
                        itemStyle: { 
                            color: d.isSim ? '#10b981' : '#3b82f6',
                            opacity: 0.6
                        },
                        name: d.name,
                        title: d.titleLevel
                    };
                });

                charts.scatter.setOption({
                    tooltip: { formatter: (p) => `${p.name}<br>年龄: ${p.value[0]}<br>职级: ${LEVEL_NAMES[Math.round(p.data.title)] || '未知'}` },
                    grid: { top: 10, bottom: 20, left: 40, right: 20 },
                    xAxis: { min: 20, max: 65, splitLine: { show: false } },
                    yAxis: { 
                        min: 0.5, max: 5.5, 
                        axisLabel: { formatter: (v) => ['','未定','二级','一级','高级','正高'][v] || '' },
                        splitLine: { lineStyle: { type: 'dashed' } }
                    },
                    series: [{
                        type: 'scatter', data: scatterData, symbolSize: 6
                    }]
                });

                // 4. Radar
                charts.radar.setOption({
                    radar: {
                        indicator: [
                            { name: '年龄拟合', max: 100 },
                            { name: '学历达标', max: 120 },
                            { name: '职称达标', max: 120 },
                            { name: '结构健康', max: 100 }
                        ],
                        radius: '65%',
                        center: ['50%', '50%']
                    },
                    series: [{
                        type: 'radar',
                        data: [
                            { 
                                value: [scores.sAge, scores.sEdu, scores.sTitle, 80], 
                                name: '当前状态',
                                itemStyle: { color: '#8b5cf6' },
                                areaStyle: { opacity: 0.2 }
                            }
                        ]
                    }]
                });
                
                const wSum = parseInt(state.weights.age) + parseInt(state.weights.edu) + parseInt(state.weights.title);
                document.getElementById('weight-alert').innerText = wSum !== 100 ? `当前总权重 ${wSum}% (建议100%)` : '';
            }

            // =========================================
            // 6. AI Logic
            // =========================================
            
            const sysPrompt = `你是一位学校人力资源专家。请根据提供的数据进行诊断。
                注意：我们设定了严格的职称年龄限制（如30岁以下不能评一级，40岁以下极少高级）。
                请输出HTML格式的文本（不要Markdown代码块），包含以下三个部分：
                <div class="ai-report-section"><div class="ai-label"><i class="fa-solid fa-check-circle text-emerald-500"></i> 核心成效</div><div class="ai-text">...</div></div>
                <div class="ai-report-section"><div class="ai-label"><i class="fa-solid fa-triangle-exclamation text-orange-500"></i> 潜在风险</div><div class="ai-text">...</div></div>
                <div class="ai-report-section"><div class="ai-label"><i class="fa-solid fa-lightbulb text-blue-500"></i> 改进建议</div><div class="ai-text">...</div></div>`;

            async function runAI() {
                const btn = document.getElementById('btn-ai');
                const btnReason = document.getElementById('btn-reason');
                const out = document.getElementById('ai-content');
                
                btn.disabled = true;
                btnReason.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> AI 思考中...';
                
                const reasonBox = document.getElementById('reasoning-box');
                if(reasonBox) reasonBox.style.display = 'none';

                const baseRes = calcMetrics(baseData);
                const currentRes = calcMetrics();

                const userPrompt = `
                    请对比分析【现状】与【模拟调整后】的数据：

                    【现状 (调整前)】
                    - 总人数: ${baseRes.metrics.count}
                    - 平均年龄: ${baseRes.metrics.avgAge.toFixed(1)}
                    - 硕士率: ${baseRes.metrics.masterRate.toFixed(1)}%
                    - 高级职称率: ${baseRes.metrics.seniorRate.toFixed(1)}%
                    - TQI得分: ${baseRes.scores.final}

                    【模拟后 (调整后)】
                    - 总人数: ${currentRes.metrics.count} (新增 ${currentRes.simCount} 人)
                    - 平均年龄: ${currentRes.metrics.avgAge.toFixed(1)}
                    - 硕士率: ${currentRes.metrics.masterRate.toFixed(1)}%
                    - 高级职称率: ${currentRes.metrics.seniorRate.toFixed(1)}%
                    - TQI得分: ${currentRes.scores.final}

                    目标设定：最佳年龄 ${state.opt.age}岁，目标硕士率 ${state.opt.edu}%，目标高职率 ${state.opt.title}%。
                    
                    请重点分析招聘带来的具体改进（量化对比），并指出仍存在的结构性风险。
                `;

                try {
                    const resp = await fetch(API_URL, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${DEEPSEEK_KEY}` },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-V3.2", // 分析任务使用 V3.2
                            messages: [
                                { role: "system", content: sysPrompt },
                                { role: "user", content: userPrompt }
                            ],
                            stream: false
                        })
                    });
                    const json = await resp.json();
                    let content = json.choices[0].message.content;
                    content = content.replace(/<think>[\s\S]*?<\/think>/g, '');
                    content = content.replace(/```html/g, '').replace(/```/g, '');
                    out.innerHTML = content;
                } catch(e) {
                    out.innerHTML = `<div class="text-red-500">AI连接失败: ${e.message}</div>`;
                }

                btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles text-blue-500"></i> AI 诊断';
                btn.disabled = false;
                btnReason.disabled = false;
            }

            async function runDeepReasoning() {
                const btn = document.getElementById('btn-ai');
                const btnReason = document.getElementById('btn-reason');
                const out = document.getElementById('ai-content');
                
                btn.disabled = true;
                btnReason.disabled = true;
                btnReason.innerHTML = '<i class="fa-solid fa-brain fa-bounce"></i> AI 推演中...';
                
                out.innerHTML = '';
                
                let reasonBox = document.createElement('div');
                reasonBox.id = 'reasoning-box';
                reasonBox.className = 'reasoning-container';
                reasonBox.innerHTML = `<div class="reasoning-title"><i class="fa-solid fa-microchip"></i> AI 思维链 <span class="thinking-dot"></span></div><div class="reasoning-content" id="r-content"></div>`;
                out.appendChild(reasonBox);
                reasonBox.style.display = 'block';

                let resultBox = document.createElement('div');
                resultBox.id = 'result-box';
                out.appendChild(resultBox);

                const rContent = document.getElementById('r-content');
                
                const baseRes = calcMetrics(baseData);
                const currentRes = calcMetrics();
                
                const userPrompt = `
                    请对学校师资结构进行深度战略推演，对比现状与模拟方案：

                    【现状数据 (Baseline)】
                    - 总人数: ${baseRes.metrics.count}
                    - TQI综合效能分: ${baseRes.scores.final}
                    - 平均年龄: ${baseRes.metrics.avgAge.toFixed(1)} (标准差 ${baseRes.metrics.ageStdDev.toFixed(1)})
                    - 硕士占比: ${baseRes.metrics.masterRate.toFixed(1)}%
                    - 高级职称占比: ${baseRes.metrics.seniorRate.toFixed(1)}%

                    【模拟后数据 (Simulation)】
                    - 总人数: ${currentRes.metrics.count} (本次模拟招聘 ${currentRes.simCount} 人)
                    - TQI综合效能分: ${currentRes.scores.final}
                    - 平均年龄: ${currentRes.metrics.avgAge.toFixed(1)} (标准差 ${currentRes.metrics.ageStdDev.toFixed(1)})
                    - 硕士占比: ${currentRes.metrics.masterRate.toFixed(1)}%
                    - 高级职称占比: ${currentRes.metrics.seniorRate.toFixed(1)}%

                    【战略目标】
                    - 最佳平均年龄: ${state.opt.age}岁 (理想标准差 ${state.opt.sigma})
                    - 目标硕士率: ${state.opt.edu}%
                    - 目标高职率: ${state.opt.title}%

                    请一步步深度思考：
                    1. 差异性分析：本次招聘方案对关键指标（TQI、年龄结构、高层次人才比例）的具体拉动作用是多少？是正向还是负向？
                    2. 结构演变推演：如果按照此方案执行，5-10年后师资梯队会呈现什么形态？是否存在新的断层风险（如大量青年教师同时老化拥堵）？
                    3. 战略建议：针对模拟结果的优劣，给出调整招聘策略的具体建议（如“应减少应届生，增加成熟骨干”）。
                    
                    最后输出标准的HTML格式诊断报告（包含核心成效、潜在风险、改进建议三部分，使用div class="ai-report-section"结构）。
                `;

                try {
                    const response = await fetch(API_URL, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${DEEPSEEK_KEY}` },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-R1", // 深度思考使用 R1
                            messages: [
                                { role: "system", content: sysPrompt },
                                { role: "user", content: userPrompt }
                            ],
                            stream: true
                        })
                    });

                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    let finalMarkdown = '';

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop();

                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                const jsonStr = line.slice(6);
                                if (jsonStr === '[DONE]') continue;
                                try {
                                    const json = JSON.parse(jsonStr);
                                    const delta = json.choices[0].delta;
                                    
                                    if (delta.reasoning_content) {
                                        rContent.textContent += delta.reasoning_content;
                                        reasonBox.scrollTop = reasonBox.scrollHeight;
                                    }
                                    
                                    if (delta.content) {
                                        finalMarkdown += delta.content;
                                        resultBox.innerHTML = finalMarkdown.replace(/```html/g, '').replace(/```/g, '');
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                    
                    resultBox.innerHTML = finalMarkdown.replace(/```html/g, '').replace(/```/g, '');
                    document.querySelector('.thinking-dot').style.animation = 'none';
                    document.querySelector('.thinking-dot').style.opacity = '0.5';

                } catch(e) {
                    resultBox.innerHTML += `<div class="text-red-500 mt-2">思考过程被中断: ${e.message}</div>`;
                }

                btn.disabled = false;
                btnReason.disabled = false;
                btnReason.innerHTML = '<i class="fa-solid fa-brain"></i> 深度思考';
            }

            // Chat
            const chatWin = document.getElementById('chat-window');
            function toggleChat() {
                chatWin.style.display = chatWin.style.display === 'flex' ? 'none' : 'flex';
            }
            async function sendChat() {
                const inp = document.getElementById('chat-input');
                const val = inp.value.trim();
                if(!val) return;
                
                const body = document.getElementById('chat-body');
                body.innerHTML += `<div class="chat-bubble user">${val}</div>`;
                inp.value = '';
                
                const loadId = 'l-' + Date.now();
                body.innerHTML += `<div id="${loadId}" class="chat-bubble ai">...</div>`;
                body.scrollTop = body.scrollHeight;

                const res = calcMetrics();
                const systemContent = "你是HKA学校的数据效能助手。请用简洁朴实的语言回答用户问题，除非用户特别询问，否则不必主动提及TQI计算公式。";
                const userContext = `上下文数据：
                    - 总人数: ${res.metrics.count}
                    - 平均年龄: ${res.metrics.avgAge.toFixed(1)}
                    - 硕士率: ${res.metrics.masterRate.toFixed(1)}%
                    - 高级职称率: ${res.metrics.seniorRate.toFixed(1)}%
                    - TQI: ${res.scores.final}
                    用户问题：${val}`;

                try {
                    const response = await fetch(API_URL, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${DEEPSEEK_KEY}` },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-R1",
                            messages: [
                                { role: "system", content: systemContent },
                                { role: "user", content: userContext }
                            ],
                            stream: true 
                        })
                    });

                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    let reasoningText = '';
                    let finalText = '';
                    const bubble = document.getElementById(loadId);
                    bubble.innerHTML = ''; 

                    let reasoningDetails = document.createElement('details');
                    reasoningDetails.className = 'chat-reasoning';
                    reasoningDetails.innerHTML = `<summary>AI 深度思考中...</summary><div class="chat-reasoning-text"></div>`;
                    bubble.appendChild(reasoningDetails);
                    
                    let contentDiv = document.createElement('div');
                    bubble.appendChild(contentDiv);

                    const reasoningContentDiv = reasoningDetails.querySelector('.chat-reasoning-text');

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop();

                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                const jsonStr = line.slice(6);
                                if (jsonStr === '[DONE]') continue;
                                try {
                                    const json = JSON.parse(jsonStr);
                                    const delta = json.choices[0].delta;
                                    
                                    if (delta.reasoning_content) {
                                        reasoningText += delta.reasoning_content;
                                        reasoningContentDiv.textContent = reasoningText;
                                    }
                                    if (delta.content) {
                                        finalText += delta.content;
                                        contentDiv.innerHTML = finalText.replace(/\n/g, '<br>');
                                        
                                        if(reasoningDetails.querySelector('summary').innerText.includes('思考中')) {
                                            reasoningDetails.querySelector('summary').innerText = '已完成深度思考';
                                        }
                                        body.scrollTop = body.scrollHeight; 
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                    if (!reasoningText) {
                        reasoningDetails.remove();
                    } else {
                        reasoningDetails.querySelector('summary').innerText = '已完成深度思考';
                    }

                } catch(e) {
                    document.getElementById(loadId).innerText = "网络错误或服务繁忙";
                }
                body.scrollTop = body.scrollHeight;
            }

            function resetAll() {
                state.simMode = 'A';
                state.a.count = 0;
                bindInput('in-a-count', (v)=>{ state.a.count = parseInt(v); document.getElementById('val-a-count').innerText = v; }, 'val-a-count');
                document.getElementById('in-a-count').value = 0;
                document.getElementById('ai-content').innerHTML = '<div class="h-full flex flex-col items-center justify-center text-slate-400 gap-3"><div class="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center"><i class="fa-solid fa-microchip text-xl opacity-30"></i></div><p class="text-xs">选择模式并生成诊断</p></div>';
                
                // Trigger update manually
                state.a.count = 0;
                document.getElementById('val-a-count').innerText = 0;
                update();
                
                setMode('A');
            }

            function setMode(m) {
                state.simMode = m;
                document.getElementById('mode-a').className = m==='A' ? 'tab-btn tab-active' : 'tab-btn tab-inactive';
                document.getElementById('mode-b').className = m==='B' ? 'tab-btn tab-active' : 'tab-btn tab-inactive';
                document.getElementById('panel-a').style.display = m==='A' ? 'flex' : 'none';
                document.getElementById('panel-b').style.display = m==='B' ? 'flex' : 'none';
                update();
            }

            function applyPreset(type) {
                document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
                event.target.classList.add('active');

                if (type === 'youth') {
                    updateInput('in-a-count', 20);
                    updateInput('in-a-20s', 80); updateInput('in-a-30s', 20); updateInput('in-a-40s', 0); updateInput('in-a-50s', 0);
                    updateInput('in-a-master', 30); updateInput('in-a-senior', 0);
                } else if (type === 'middle') {
                    updateInput('in-a-count', 10);
                    updateInput('in-a-20s', 10); updateInput('in-a-30s', 70); updateInput('in-a-40s', 20); updateInput('in-a-50s', 0);
                    updateInput('in-a-master', 60); updateInput('in-a-senior', 50);
                } else if (type === 'expert') {
                    updateInput('in-a-count', 3);
                    updateInput('in-a-20s', 0); updateInput('in-a-30s', 0); updateInput('in-a-40s', 50); updateInput('in-a-50s', 50);
                    updateInput('in-a-master', 100); updateInput('in-a-senior', 100);
                }
            }

            function updateInput(id, val) {
                const el = document.getElementById(id);
                el.value = val;
                el.dispatchEvent(new Event('input'));
            }

            init();
        </script>
    </body>
    </html>
    """
    
    html_content = html_template.replace("[[SILICONFLOW_KEY]]", API_KEY)
    html_content = html_content.replace("[[DATA_INSERT]]", st.session_state.final_json_str)
    
    components.html(html_content, height=900, scrolling=False)
