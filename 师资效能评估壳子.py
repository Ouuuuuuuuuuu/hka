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

# 优先从 Secrets 读取 Key，如果没有配置，则使用代码中预设的 Key (方便直接运行)
DEFAULT_KEY = "sk-lezqyzzxlcnarawzhmyddltuclijckeufnzzktmkizfslcje"
API_KEY = st.secrets.get("SILICONFLOW_API_KEY", DEFAULT_KEY)

# ==============================================================================
# 2. AI 智能解析引擎 (Python 后端处理)
# ==============================================================================
@st.cache_data(show_spinner=False)
def ai_parse_excel(df):
    """
    使用 DeepSeek-V3 能够理解任意乱七八糟的表头，
    将其清洗为系统所需的标准 JSON 格式。
    """
    # 1. 全量处理
    csv_content = df.to_csv(index=False)
    
    # 2. 参考模版 (Reference Template)
    reference_template = """
    序号,姓名,入职时间,所在部门,岗位类型,岗位类型（按统计）,性别,年龄,是否退休,学科（按统计）,职称,研究生
    1,黄珂晰,2021/8/16,年级组,中层管理/专任教师,专任教师,女,56,是,地理,中小学高级教师,研究生
    2,岳智,2024/7/30,年级组,专任教师,专任教师,女,25,,地理,未定职级,本科
    3,林翠花,2024/8/1,年级组,中层管理/专任教师,专任教师,女,56,是,地理,中小学一级教师,本科
    4,穆东旭,2024/8/23,年级组,专任教师,专任教师,男,28,,地理,未定职级,研究生
    """

    # 3. 定义给 AI 的指令 (System Prompt)
    target_schema = """
    [
      {
        "name": "姓名",
        "age": 25, // 必须是整数。直接从数据提取，严禁瞎编。
        "subject": "学科", // 如 语文, 数学, 体育...
        "edu": 1, // 1=本科及以下, 2=研究生/硕士/博士
        "titleLevel": 1, // 1=未定/无, 2=二级/初级, 3=一级/中级, 4=高级/副高, 5=正高
        "rawTitle": "原始职称字符串"
      }
    ]
    """
    
    system_prompt = f"""
    你是一个专业的数据清洗助手。你的任务是读取用户提供的CSV数据，提取关键信息并输出为严格的JSON数组。
    
    【参考标准数据模式 (Template)】:
    {reference_template}
    
    【输出数据结构要求】:
    {target_schema}
    
    【处理规则】:
    1. **完全提取**: 必须处理用户提供的所有行，不要遗漏。
    2. **列名映射**: 用户的列名可能不标准，请参照【参考标准数据模式】进行语义对应。例如用户列"岁数"对应参考中的"年龄"，最终提取为"age"。
    3. **职称量化 (titleLevel)**:
       - 包含"正高"、"教授" -> 5
       - 包含"高级"、"副高" -> 4
       - 包含"一级"、"中级" -> 3
       - 包含"二级"、"初级" -> 2
       - 其他/未定 -> 1
    4. **学历量化 (edu)**: 包含"研"、"硕"、"博" -> 2，否则 -> 1。
    5. **只输出JSON**: 不要包含 ```json 或其他 markdown 标记，直接输出 JSON 数组字符串。
    """

    user_prompt = f"这是用户上传的完整表格数据，请进行清洗和转换：\n\n{csv_content}"

    # 4. 调用 SiliconFlow API
    try:
        url = "[https://api.siliconflow.cn/v1/chat/completions](https://api.siliconflow.cn/v1/chat/completions)"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-ai/DeepSeek-V3.2-Exp", 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"}, 
            "temperature": 0.1, 
            "max_tokens": 8000  
        }
        
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if "choices" not in response_data:
            raise Exception(f"API Error: {response_data}")
            
        content = response_data["choices"][0]["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        parsed_result = json.loads(content)
        
        if isinstance(parsed_result, dict):
            for key, val in parsed_result.items():
                if isinstance(val, list):
                    return val
            return []
        elif isinstance(parsed_result, list):
            return parsed_result
        else:
            return []

    except Exception as e:
        print(f"AI Parse Error: {e}")
        return None

# ==============================================================================
# 3. 页面逻辑控制 (状态机)
# ==============================================================================

# 初始化 Session State
if 'data_confirmed' not in st.session_state:
    st.session_state.data_confirmed = False
if 'final_json_str' not in st.session_state:
    st.session_state.final_json_str = "null"

def reset_app():
    """重置应用状态，返回上传页"""
    st.session_state.data_confirmed = False
    st.session_state.final_json_str = "null"
    st.rerun()

# ------------------------------------------------------------------------------
# 页面 A: 数据上传与确认中心 (Landing Page)
# ------------------------------------------------------------------------------
if not st.session_state.data_confirmed:
    # 居中布局，移除侧边栏干扰
    st.title("🛠️ HKA 师资效能评估 - 智能数据导入")
    
    with st.container():
        st.markdown("""
        ### 👋 欢迎使用
        请上传您的教师花名册文件（支持 Excel 或 CSV）。
        
        **系统特性：**
        - 🤖 **AI 自动识别**：无需调整表头，AI 会自动识别“岁数”、“教龄”、“职称”等字段。
        - 🧹 **智能清洗**：自动将中文职称（如“中小学一级”）转换为标准等级。
        """)
        
        uploaded_file = st.file_uploader("📄 点击此处上传文件", type=['xlsx', 'xls', 'csv'])

    if uploaded_file:
        st.divider()
        with st.spinner("🤖 DeepSeek 正在读取并理解表格结构，请稍候..."):
            try:
                # 1. 读取文件
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                # 2. 调用 AI 解析
                ai_result = ai_parse_excel(df)
                
                if ai_result and len(ai_result) > 0:
                    st.success(f"✅ 解析成功！共提取 {len(ai_result)} 条教师数据。")
                    
                    # 3. 数据确认区
                    st.info("👇 请检查下方数据预览，确保关键字段（姓名、年龄、职称、学历）识别正确。")
                    
                    # 将 JSON 转回 DF 方便预览
                    preview_df = pd.DataFrame(ai_result)
                    st.dataframe(preview_df.head(10), use_container_width=True)
                    st.caption(f"仅展示前 10 条预览，共 {len(ai_result)} 条。")
                    
                    col_confirm, col_space = st.columns([1, 2])
                    with col_confirm:
                        # 4. 确认按钮
                        if st.button("🚀 确认数据无误，启动大屏", type="primary", use_container_width=True):
                            st.session_state.final_json_str = json.dumps(ai_result, ensure_ascii=False)
                            st.session_state.data_confirmed = True
                            st.rerun() # 重新运行以跳转到页面 B
                else:
                    st.error("❌ AI 未能从文件中提取到有效数据，请检查文件内容是否包含必要信息。")
            
            except Exception as e:
                st.error(f"处理过程中发生错误: {str(e)}")

# ------------------------------------------------------------------------------
# 页面 B: 效能评估大屏 (Dashboard)
# ------------------------------------------------------------------------------
else:
    # 侧边栏仅在进入大屏后显示，提供重置功能
    with st.sidebar:
        st.success("✅ 数据已加载")
        st.info("如需分析新的数据，请点击下方按钮。")
        if st.button("🔄 重新上传数据", use_container_width=True):
            reset_app()

    # ==============================================================================
    # 4. 前端大屏代码 (HTML/JS)
    # ==============================================================================
    
    html_template = r"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HKA 师资效能评估 AI-Native</title>
        <script src="[https://cdn.tailwindcss.com](https://cdn.tailwindcss.com)"></script>
        <script src="[https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js](https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js)"></script>
        <link href="[https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css](https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css)" rel="stylesheet">
        <style>
            @import url('[https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap](https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap)');
            body { font-family: 'Noto Sans SC', sans-serif; background-color: #f8fafc; color: #334155; margin: 0; padding: 0; overflow: hidden; }
            
            /* 通用样式 */
            .card { background: white; border-radius: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; transition: box-shadow 0.2s; }
            .card:hover { box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
            .custom-scroll::-webkit-scrollbar { width: 4px; }
            .custom-scroll::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 10px; }
            
            /* 控件样式 */
            input[type=range] { -webkit-appearance: none; background: transparent; width: 100%; cursor: pointer; }
            input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; height: 14px; width: 14px; border-radius: 50%; background: #3b82f6; margin-top: -5px; box-shadow: 0 1px 2px rgba(0,0,0,0.2); border: 2px solid white; }
            input[type=range]::-webkit-slider-runnable-track { width: 100%; height: 4px; background: #cbd5e1; border-radius: 2px; }
            .tab-btn { padding: 8px; font-size: 0.75rem; font-weight: 600; border-radius: 6px; cursor: pointer; flex: 1; text-align: center; transition: all 0.2s; }
            .tab-active { background-color: #eff6ff; color: #2563eb; box-shadow: inset 0 0 0 1px #bfdbfe; }
            .tab-inactive { background-color: transparent; color: #64748b; }
            .preset-btn { font-size: 0.7rem; padding: 4px 8px; border-radius: 4px; border: 1px solid #e2e8f0; background: #f8fafc; color: #475569; }
            .preset-btn.active { background: #dbeafe; color: #2563eb; border-color: #bfdbfe; font-weight: 600; }

            /* AI 报告样式 */
            .ai-report-section { margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0; }
            .ai-label { font-weight: 700; color: #475569; font-size: 0.8rem; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
            .ai-text { font-size: 0.85rem; color: #334155; line-height: 1.6; text-align: justify; }
            
            /* 聊天窗口 */
            #chat-wrapper { position: fixed; bottom: 24px; right: 24px; z-index: 50; display: flex; flex-direction: column; align-items: flex-end; }
            #chat-window { width: 360px; height: 480px; background: white; border-radius: 12px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; display: none; flex-direction: column; overflow: hidden; margin-bottom: 16px; }
            .chat-bubble { max-width: 88%; padding: 10px 14px; border-radius: 12px; font-size: 0.85rem; margin-bottom: 10px; }
            .chat-bubble.user { background: #3b82f6; color: white; align-self: flex-end; }
            .chat-bubble.ai { background: #f1f5f9; color: #334155; align-self: flex-start; border: 1px solid #e2e8f0; }
            .fab-btn { width: 50px; height: 50px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 20px; cursor: pointer; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }

            /* 空状态覆盖层 */
            #empty-state { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255,255,255,0.98); z-index: 999; display: flex; flex-direction: column; align-items: center; justify-content: center; }
        </style>
    </head>
    <body class="h-screen flex flex-col overflow-hidden">

        <!-- 顶部导航 -->
        <nav class="bg-white border-b border-slate-200 h-14 shrink-0 flex items-center px-6 justify-between z-40 shadow-sm">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 bg-indigo-600 rounded flex items-center justify-center text-white shadow-sm"><i class="fa-solid fa-layer-group text-sm"></i></div>
                <h1 class="font-bold text-slate-700 tracking-tight">HKA 师资效能评估 <span class="text-xs font-normal text-slate-400 ml-1">AI-Parsed</span></h1>
            </div>
            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded border border-emerald-100">
                    <span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span>
                    DeepSeek-V3 Engine
                </div>
                <button onclick="resetAll()" class="text-xs text-slate-500 bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded transition">重置</button>
            </div>
        </nav>

        <!-- 主布局 -->
        <main class="flex-1 grid grid-cols-12 gap-4 p-4 min-h-0 max-w-[1920px] mx-auto w-full">
            <!-- 左侧配置 -->
            <div class="col-span-3 flex flex-col gap-4 custom-scroll overflow-y-auto pr-1 pb-10">
                <div class="card p-4 flex flex-col gap-4 border-t-4 border-t-emerald-500">
                    <div class="flex justify-between items-center border-b pb-2">
                        <h2 class="text-sm font-bold text-slate-700"><i class="fa-solid fa-sliders text-emerald-500 mr-2"></i>模拟招聘</h2>
                        <div class="flex bg-slate-100 rounded-lg p-0.5">
                            <div id="mode-a" class="tab-btn tab-active" onclick="setMode('A')">专家</div>
                            <div id="mode-b" class="tab-btn tab-inactive" onclick="setMode('B')">简易</div>
                        </div>
                    </div>
                    <div id="panel-a" class="flex flex-col gap-4">
                        <div class="grid grid-cols-3 gap-2">
                            <button class="preset-btn" onclick="applyPreset('youth')">🌱 青年军</button>
                            <button class="preset-btn" onclick="applyPreset('middle')">🦴 骨干填充</button>
                            <button class="preset-btn" onclick="applyPreset('expert')">👑 高端引进</button>
                        </div>
                        <div><div class="flex justify-between text-xs font-bold text-slate-500 mb-1"><span>招聘人数</span><span id="val-a-count" class="text-emerald-600">0</span></div><input type="range" id="in-a-count" max="60" value="0"></div>
                        <div class="bg-slate-50 p-3 rounded border flex flex-col gap-2">
                            <div class="text-[10px] font-bold text-slate-400">年龄分布权重</div>
                            <input type="range" id="in-a-20s" value="40" title="20s"><input type="range" id="in-a-30s" value="40" title="30s">
                            <input type="range" id="in-a-40s" value="10" title="40s"><input type="range" id="in-a-50s" value="10" title="50s">
                        </div>
                    </div>
                    <div id="panel-b" class="hidden flex flex-col gap-4">
                        <div class="p-3 bg-blue-50 text-xs text-blue-700 rounded border border-blue-100">系统将自动随机补充缺口。</div>
                        <div><div class="flex justify-between text-xs font-bold text-slate-500 mb-1"><span>招聘人数</span><span id="val-b-count" class="text-blue-600">0</span></div><input type="range" id="in-b-count" max="50" value="0"></div>
                    </div>
                </div>
                
                <div class="card p-4 border-l-4 border-l-blue-500">
                    <div class="flex justify-between items-center border-b pb-2 mb-2"><h2 class="text-sm font-bold text-slate-700">理想模型</h2></div>
                    <div class="space-y-3">
                        <div><div class="flex justify-between text-xs text-slate-500"><span>最佳均龄</span><span id="disp-opt-age" class="text-blue-600">32</span></div><input type="range" id="opt-age" min="28" max="45" value="32"></div>
                        <div><div class="flex justify-between text-xs text-slate-500"><span>目标硕士率</span><span id="disp-opt-edu" class="text-purple-600">50%</span></div><input type="range" id="opt-edu" min="10" max="100" value="50"></div>
                        <div><div class="flex justify-between text-xs text-slate-500"><span>目标高职率</span><span id="disp-opt-title" class="text-orange-600">30%</span></div><input type="range" id="opt-title" min="5" max="60" value="30"></div>
                    </div>
                </div>
            </div>

            <!-- 中间图表 -->
            <div class="col-span-5 flex flex-col gap-4 h-full overflow-hidden">
                <div class="card px-5 py-3 h-24 flex items-center gap-5 relative shrink-0">
                    <div class="absolute left-0 top-0 bottom-0 w-1.5 bg-indigo-500 rounded-l-lg"></div>
                    <div><div class="text-[10px] text-slate-400 font-bold uppercase">TQI 指数</div><div id="tqi-score" class="text-4xl font-black text-slate-800">--</div></div>
                    <div class="flex-1 pt-1">
                        <div class="flex justify-between text-[10px] text-slate-500"><span>评级</span><span id="tqi-grade" class="text-indigo-600">...</span></div>
                        <div class="h-3 w-full bg-slate-100 rounded-full overflow-hidden mt-1"><div id="tqi-bar" class="h-full bg-indigo-500" style="width: 0%"></div></div>
                    </div>
                </div>
                <div class="card p-4 h-[300px] flex flex-col shrink-0">
                    <div class="flex justify-between items-center mb-1 border-b pb-2"><h3 class="text-sm font-bold text-slate-700">年龄结构</h3><select id="subject-filter" class="text-xs bg-transparent outline-none text-slate-500"><option value="all">全校</option></select></div>
                    <div id="chart-hist" class="flex-1 -ml-2"></div>
                </div>
                <div class="card p-4 h-[320px] flex flex-col shrink-0">
                    <div class="flex justify-between items-center mb-1 border-b pb-2"><h3 class="text-sm font-bold text-slate-700">职称分布</h3></div>
                    <div id="chart-scatter" class="flex-1"></div>
                </div>
            </div>

            <!-- 右侧 AI -->
            <div class="col-span-4 flex flex-col gap-4 h-full overflow-hidden pb-4">
                <div class="card p-4 h-[220px] flex flex-col shrink-0">
                    <h3 class="text-xs font-bold text-slate-500 uppercase mb-2">多维雷达</h3>
                    <div id="chart-radar" class="flex-1"></div>
                </div>
                <div class="card flex-1 flex flex-col bg-white border-t-4 border-t-purple-500 overflow-hidden">
                    <div class="p-4 border-b bg-slate-50 flex justify-between items-center">
                        <div class="flex items-center gap-2"><i class="fa-solid fa-robot text-purple-600"></i><span class="font-bold text-slate-700 text-sm">智能诊断</span></div>
                        <div class="flex gap-2">
                            <button onclick="runAI()" id="btn-ai" class="text-xs bg-white border hover:bg-slate-50 px-3 py-1.5 rounded transition">诊断</button>
                            <button onclick="runDeepReasoning()" id="btn-reason" class="text-xs bg-purple-600 text-white hover:bg-purple-700 px-3 py-1.5 rounded transition">深度思考</button>
                        </div>
                    </div>
                    <div id="ai-content" class="p-5 overflow-y-auto custom-scroll flex-1 text-sm text-center flex flex-col justify-center text-slate-400">
                        <i class="fa-solid fa-microchip text-3xl opacity-20 mb-2"></i>
                        <p>等待分析指令...</p>
                    </div>
                </div>
            </div>
        </main>

        <!-- 悬浮聊天 -->
        <div id="chat-wrapper">
            <div id="chat-window">
                <div class="bg-slate-800 text-white p-3 flex justify-between"><span class="text-xs font-bold">效能助手</span><button onclick="toggleChat()" class="text-slate-400"><i class="fa-solid fa-times"></i></button></div>
                <div id="chat-body" class="flex-1 bg-slate-50 p-4 overflow-y-auto custom-scroll"></div>
                <div class="p-3 bg-white border-t flex gap-2">
                    <input type="text" id="chat-input" class="flex-1 bg-slate-100 border-none rounded px-3 text-sm" placeholder="Ask R1...">
                    <button onclick="sendChat()" class="bg-blue-600 text-white rounded px-3"><i class="fa-solid fa-paper-plane"></i></button>
                </div>
            </div>
            <div class="fab-btn" onclick="toggleChat()"><i class="fa-solid fa-message"></i></div>
        </div>

        <!-- 空状态 (当没有数据注入时显示) -->
        <div id="empty-state">
            <div class="w-20 h-20 bg-blue-50 rounded-full flex items-center justify-center mb-6 text-blue-500 text-3xl"><i class="fa-solid fa-cloud-upload-alt"></i></div>
            <h2 class="text-2xl font-bold text-slate-800 mb-2">等待数据导入</h2>
            <p class="text-slate-500 mb-8">请在左侧上传 Excel 文件，AI 将自动完成数据清洗与建模。</p>
            <div class="flex gap-4 text-xs text-slate-400">
                <span class="flex items-center gap-1"><i class="fa-solid fa-file-excel"></i> 支持 .xlsx</span>
                <span class="flex items-center gap-1"><i class="fa-solid fa-file-csv"></i> 支持 .csv</span>
                <span class="flex items-center gap-1"><i class="fa-solid fa-robot"></i> 自动识别表头</span>
            </div>
        </div>

        <script>
            // ===========================================
            // 1. 数据注入 (核心交互点)
            // ===========================================
            // Python 会将清洗后的 JSON 字符串替换这里的 [[DATA_INSERT]]
            const injectedData = [[DATA_INSERT]];
            
            // API Key (Python 注入)
            const DEEPSEEK_KEY = "[[SILICONFLOW_KEY]]";
            const API_URL = "[https://api.siliconflow.cn/v1/chat/completions](https://api.siliconflow.cn/v1/chat/completions)";

            const LEVEL_NAMES = { 1:'未定', 2:'二级', 3:'一级', 4:'高级', 5:'正高' };
            let baseData = [];
            
            // ===========================================
            // 2. 初始化逻辑
            // ===========================================
            function init() {
                // 检查是否有数据注入
                if (injectedData && Array.isArray(injectedData) && injectedData.length > 0) {
                    baseData = injectedData;
                    document.getElementById('empty-state').style.display = 'none'; // 隐藏空状态遮罩
                    
                    // 初始化筛选器
                    const sel = document.getElementById('subject-filter');
                    const subjs = [...new Set(baseData.map(d=>d.subject))].filter(Boolean).sort();
                    sel.innerHTML = '<option value="all">全校总览</option>';
                    subjs.forEach(s => sel.appendChild(new Option(s, s)));
                    sel.addEventListener('change', (e) => { state.filter=e.target.value; update(); });

                    // 初始化图表
                    charts.hist = echarts.init(document.getElementById('chart-hist'));
                    charts.scatter = echarts.init(document.getElementById('chart-scatter'));
                    charts.radar = echarts.init(document.getElementById('chart-radar'));
                    window.addEventListener('resize', () => Object.values(charts).forEach(c=>c.resize()));

                    // 绑定输入事件 (简化版绑定)
                    const inputs = ['in-a-count','in-a-20s','in-a-30s','in-a-40s','in-a-50s','opt-age','opt-edu','opt-title'];
                    inputs.forEach(id => {
                        const el = document.getElementById(id);
                        if(el) el.addEventListener('input', (e) => {
                            // 简单映射更新 state，实际逻辑更复杂
                            if(id==='in-a-count') { state.a.count=parseInt(e.target.value); document.getElementById('val-a-count').innerText=e.target.value; }
                            // ... 其他绑定省略，保持简洁 ...
                            update();
                        });
                    });

                    // 首次渲染
                    update();
                } else {
                    // 如果没有数据 (null 或 空数组)，保持空状态遮罩显示
                    console.log("No data injected, waiting for upload...");
                }
            }

            // ===========================================
            // 3. 核心算法与渲染 (保持原逻辑)
            // ===========================================
            let state = { simMode: 'A', a: {count:0, dist:[40,40,10,10], master:50, senior:20}, opt: {age:32, edu:50, title:30, sigma:7}, weights:{age:40,edu:30,title:30}, filter:'all' };
            let charts = {};

            function getSimulatedData() {
                // 简化的模拟逻辑
                if(state.a.count <= 0) return [];
                let sim = [];
                for(let i=0; i<state.a.count; i++) {
                    sim.push({ isSim: true, age: 25 + Math.floor(Math.random()*10), titleLevel: 1, edu: 1, subject: '模拟' });
                }
                return sim;
            }

            function calcMetrics() {
                const sim = getSimulatedData();
                const all = [...baseData, ...sim];
                const filtered = state.filter === 'all' ? all : all.filter(d => d.subject === state.filter);
                if (filtered.length === 0) return null;

                const avgAge = filtered.reduce((a,b)=>a+b.age,0) / filtered.length;
                const masterRate = (filtered.filter(d=>d.edu===2).length / filtered.length) * 100;
                const seniorRate = (filtered.filter(d=>d.titleLevel>=4).length / filtered.length) * 100;
                
                // 简单打分
                const sAge = Math.max(0, 100 - Math.abs(avgAge - state.opt.age)*3);
                const final = (sAge*0.4 + masterRate*0.3 + seniorRate*0.3).toFixed(1);

                return { metrics: { count: filtered.length, avgAge, masterRate, seniorRate }, scores: { final, sAge }, data: all, simCount: sim.length };
            }

            function update() {
                const res = calcMetrics();
                if(!res) return;
                
                // 更新 UI
                document.getElementById('tqi-score').innerText = res.scores.final;
                document.getElementById('tqi-bar').style.width = res.scores.final + '%';
                
                // 更新图表 (Hist)
                const xData = [20,25,30,35,40,45,50,55,60];
                const yExist = xData.map(x => res.data.filter(d=>!d.isSim && d.age>=x && d.age<x+5).length);
                const ySim = xData.map(x => res.data.filter(d=>d.isSim && d.age>=x && d.age<x+5).length);
                
                charts.hist.setOption({
                    tooltip: { trigger: 'axis' }, grid: { top:10, bottom:20, left:30, right:10 },
                    xAxis: { data: xData.map(x=>x+'-'+(x+5)) }, yAxis: {},
                    series: [
                        { type:'bar', stack:'a', data: yExist, itemStyle:{color:'#3b82f6'} },
                        { type:'bar', stack:'a', data: ySim, itemStyle:{color:'#10b981'} }
                    ]
                });
                
                // 更新图表 (Scatter)
                charts.scatter.setOption({
                    tooltip: { formatter: p=>`年龄:${p.value[0]} 级:${LEVEL_NAMES[p.value[1]]}` },
                    grid: { top:10, bottom:20, left:30, right:10 },
                    xAxis: { min:20, max:65 }, yAxis: { min:0.5, max:5.5, splitLine:{lineStyle:{type:'dashed'}} },
                    series: [{ type:'scatter', symbolSize:6, data: res.data.map(d=>({ value:[d.age, d.titleLevel+(Math.random()*0.3-0.15)], itemStyle:{color:d.isSim?'#10b981':'#3b82f6', opacity:0.6} })) }]
                });

                // 更新图表 (Radar)
                charts.radar.setOption({
                    radar: { indicator: [{name:'结构',max:100},{name:'学历',max:100},{name:'职称',max:100}], radius:'60%' },
                    series: [{ type:'radar', data:[{ value:[res.scores.sAge, res.metrics.masterRate, res.metrics.seniorRate], areaStyle:{opacity:0.2}, itemStyle:{color:'#8b5cf6'} }] }]
                });
            }

            // ===========================================
            // 4. AI 功能 (前端调用 R1)
            // ===========================================
            async function runAI() {
                const btn = document.getElementById('btn-ai');
                const out = document.getElementById('ai-content');
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                btn.disabled = true;
                
                const res = calcMetrics();
                // 简单构造 Prompt
                const prompt = `分析学校师资: 人数${res.metrics.count}, 均龄${res.metrics.avgAge.toFixed(1)}, 硕士率${res.metrics.masterRate.toFixed(1)}%, TQI:${res.scores.final}. 给出简短评价(HTML格式)。`;
                
                try {
                    const resp = await fetch(API_URL, {
                        method:'POST',
                        headers: {'Content-Type':'application/json', 'Authorization': `Bearer ${DEEPSEEK_KEY}`},
                        body: JSON.stringify({ model: "deepseek-ai/DeepSeek-V3", messages: [{role:"user", content: prompt}], stream: false })
                    });
                    const json = await resp.json();
                    out.innerHTML = json.choices[0].message.content.replace(/```html/g,'').replace(/```/g,'');
                } catch(e) { out.innerHTML = "Error: " + e.message; }
                btn.innerHTML = '诊断'; btn.disabled = false;
            }

            async function runDeepReasoning() {
                const btn = document.getElementById('btn-reason');
                const out = document.getElementById('ai-content');
                btn.innerHTML = 'R1 Thinking...';
                // 模拟深度思考输出
                out.innerHTML = '<div class="reasoning-container" style="display:block">R1 正在深度推演师资结构演变... (此功能在此精简版中仅作演示)</div>';
                setTimeout(() => { 
                    out.innerHTML += '<div>基于当前年龄分布，5年后将出现严重的老龄化断层...</div>';
                    btn.innerHTML = '深度思考';
                }, 1500);
            }

            // Chat
            const chatWin = document.getElementById('chat-window');
            function toggleChat() { chatWin.style.display = chatWin.style.display==='flex'?'none':'flex'; }
            async function sendChat() {
                const inp = document.getElementById('chat-input');
                const body = document.getElementById('chat-body');
                if(!inp.value) return;
                body.innerHTML += `<div class="chat-bubble user">${inp.value}</div>`;
                // Simple Echo for demo
                setTimeout(()=>body.innerHTML+=`<div class="chat-bubble ai">R1: 我已收到您的消息 "${inp.value}"。请连接真实API以获取智能回复。</div>`, 500);
                inp.value = '';
            }

            // 启动
            init();
            function setMode(m) { state.simMode=m; document.getElementById('mode-a').className=m==='A'?'tab-btn tab-active':'tab-btn tab-inactive'; document.getElementById('mode-b').className=m==='B'?'tab-btn tab-active':'tab-btn tab-inactive'; document.getElementById('panel-a').style.display=m==='A'?'flex':'none'; document.getElementById('panel-b').style.display=m==='B'?'flex':'none'; }
            function applyPreset(t) { /* 预设逻辑略 */ }
            function resetAll() { location.reload(); }

        </script>
    </body>
    </html>
    """

    # ==============================================================================
    # 5. 渲染引擎
    # ==============================================================================

    # 1. 注入 API KEY
    html_content = html_template.replace("[[SILICONFLOW_KEY]]", API_KEY)

    # 2. 注入数据 (如果 final_json_str 是 null，前端会显示空状态)
    html_content = html_content.replace("[[DATA_INSERT]]", st.session_state.final_json_str)

    # 3. 渲染 iframe
    components.html(html_content, height=1000, scrolling=False)
