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
# 2. 后端功能函数
# ==============================================================================

@st.cache_data(show_spinner=False)
def ai_parse_excel(df):
    """
    清洗 Excel/CSV 数据，返回标准 JSON List
    """
    # 1. 全量处理
    try:
        csv_content = df.to_csv(index=False)
    except Exception as e:
        return None, f"数据转换CSV失败: {str(e)}"
    
    # 2. 参考模版
    reference_template = """
    序号,姓名,入职时间,所在部门,岗位类型,岗位类型（按统计）,性别,年龄,是否退休,学科（按统计）,职称,研究生
    1,黄珂晰,2021/8/16,年级组,中层管理/专任教师,专任教师,女,56,是,地理,中小学高级教师,研究生
    2,岳智,2024/7/30,年级组,专任教师,专任教师,女,25,,地理,未定职级,本科
    """

    # 3. System Prompt
    target_schema = """
    [
      {
        "name": "姓名",
        "age": 25, // 整数
        "subject": "学科", 
        "edu": 1, // 1=本科, 2=硕博
        "titleLevel": 1, // 1=未定, 2=初级, 3=中级, 4=高级, 5=正高
        "rawTitle": "原始职称"
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
    1. **完全提取**: 处理用户提供的所有行。
    2. **列名映射**: 语义对应，例如"岁数"->"age"。
    3. **职称量化 (titleLevel)**: 正高/教授->5, 高级/副高->4, 一级/中级->3, 二级/初级->2, 其他->1。
    4. **学历量化 (edu)**: 研/硕/博 -> 2，否则 -> 1。
    5. **只输出JSON**: 不要包含 markdown 标记。
    """

    user_prompt = f"这是用户上传的完整表格数据，请进行清洗和转换：\n\n{csv_content}"

    # 4. 调用 SiliconFlow API (修复了 URL 格式错误)
    try:
        url = "https://api.siliconflow.cn/v1/chat/completions"  # <--- 已修复此处
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-ai/DeepSeek-V3", 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"}, 
            "temperature": 0.1, 
            "max_tokens": 8000  
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code != 200:
            return None, f"API请求失败 (Code: {response.status_code}): {response.text}"

        response_data = response.json()
        
        if "choices" not in response_data:
            error_msg = response_data.get("error", {}).get("message", str(response_data))
            return None, f"API 返回错误: {error_msg}"
            
        content = response_data["choices"][0]["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed_result = json.loads(content)
        except json.JSONDecodeError:
            return None, "AI 返回的数据不是合法的 JSON 格式"
        
        final_list = []
        if isinstance(parsed_result, dict):
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
        请上传您的教师花名册文件（支持 Excel 或 CSV）。
        """)
        
        uploaded_file = st.file_uploader("📄 点击此处上传文件", type=['xlsx', 'xls', 'csv'])

    if uploaded_file:
        st.divider()
        with st.spinner("🤖 DeepSeek 正在读取并理解表格结构，请稍候..."):
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                # 截断数据以防 Token 溢出 (建议生产环境增加此保护)
                if len(df) > 100:
                    st.warning(f"⚠️ 数据量较大 ({len(df)}行)，仅截取前100行进行演示处理。")
                    df = df.head(100)

                ai_result, error_msg = ai_parse_excel(df)
                
                if ai_result and len(ai_result) > 0:
                    st.success(f"✅ 解析成功！提取 {len(ai_result)} 条数据。")
                    
                    preview_df = pd.DataFrame(ai_result)
                    st.dataframe(preview_df.head(10), use_container_width=True)
                    st.caption(f"预览前 10 条，共 {len(ai_result)} 条。")
                    
                    if st.button("🚀 确认并启动大屏", type="primary", use_container_width=True):
                        st.session_state.final_json_str = json.dumps(ai_result, ensure_ascii=False)
                        st.session_state.data_confirmed = True
                        st.rerun()
                else:
                    st.error(f"❌ 数据解析失败: {error_msg}")
            
            except Exception as e:
                st.error(f"处理错误: {str(e)}")

# ------------------------------------------------------------------------------
# 页面 B: 效能评估大屏
# ------------------------------------------------------------------------------
else:
    with st.sidebar:
        st.success("✅ 数据已加载")
        if st.button("🔄 重新上传", use_container_width=True):
            reset_app()

    # HTML 模版：修复了 CDN 链接和 API_URL 的格式错误
    html_template = r"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HKA Dashboard</title>
        <!-- 修复：移除了多余的 Markdown 标记 []() -->
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
            body { font-family: 'Noto Sans SC', sans-serif; background-color: #f8fafc; color: #334155; margin: 0; padding: 0; overflow: hidden; }
            .card { background: white; border-radius: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }
            .custom-scroll::-webkit-scrollbar { width: 4px; }
            .custom-scroll::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 10px; }
            
            /* 简化样式以确保稳定性 */
            .tab-btn { padding: 8px; font-size: 0.75rem; font-weight: 600; border-radius: 6px; cursor: pointer; flex: 1; text-align: center; }
            .tab-active { background-color: #eff6ff; color: #2563eb; }
            .tab-inactive { background-color: transparent; color: #64748b; }
            
            #chat-wrapper { position: fixed; bottom: 24px; right: 24px; z-index: 50; display: flex; flex-direction: column; align-items: flex-end; }
            #chat-window { width: 360px; height: 480px; background: white; border-radius: 12px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); display: none; flex-direction: column; margin-bottom: 16px; border: 1px solid #e2e8f0; }
            .chat-bubble { max-width: 88%; padding: 10px 14px; border-radius: 12px; font-size: 0.85rem; margin-bottom: 10px; }
            .chat-bubble.user { background: #3b82f6; color: white; align-self: flex-end; }
            .chat-bubble.ai { background: #f1f5f9; color: #334155; align-self: flex-start; }
            .fab-btn { width: 50px; height: 50px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 20px; cursor: pointer; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        </style>
    </head>
    <body class="h-screen flex flex-col overflow-hidden">
        <nav class="bg-white border-b h-14 shrink-0 flex items-center px-6 justify-between z-40">
            <h1 class="font-bold text-slate-700">HKA 师资效能评估</h1>
            <div class="text-xs text-emerald-600 bg-emerald-50 px-2 py-1 rounded">DeepSeek-V3 Engine</div>
        </nav>

        <main class="flex-1 grid grid-cols-12 gap-4 p-4 min-h-0 w-full">
            <!-- 左侧控制面板 -->
            <div class="col-span-3 flex flex-col gap-4 custom-scroll overflow-y-auto pr-1">
                <div class="card p-4">
                    <h2 class="text-sm font-bold text-slate-700 mb-3">模拟招聘</h2>
                    <div class="flex bg-slate-100 rounded-lg p-0.5 mb-3">
                        <div id="mode-a" class="tab-btn tab-active" onclick="setMode('A')">专家</div>
                        <div id="mode-b" class="tab-btn tab-inactive" onclick="setMode('B')">简易</div>
                    </div>
                    <div id="panel-a" class="flex flex-col gap-3">
                         <div>
                            <div class="flex justify-between text-xs text-slate-500 mb-1"><span>新增人数</span><span id="val-count">0</span></div>
                            <input type="range" id="in-count" max="50" value="0" class="w-full">
                        </div>
                    </div>
                </div>
                
                <div class="card p-4">
                    <h2 class="text-sm font-bold text-slate-700 mb-3">目标设定</h2>
                    <div class="space-y-3">
                        <div><div class="flex justify-between text-xs text-slate-500"><span>目标均龄</span><span id="val-age">32</span></div><input type="range" id="opt-age" min="25" max="45" value="32" class="w-full"></div>
                    </div>
                </div>
            </div>

            <!-- 中间图表 -->
            <div class="col-span-6 flex flex-col gap-4">
                <div class="card p-4 h-24 flex items-center gap-4">
                    <div><div class="text-[10px] text-slate-400 font-bold uppercase">TQI 指数</div><div id="tqi-score" class="text-4xl font-black text-slate-800">--</div></div>
                    <div class="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden"><div id="tqi-bar" class="h-full bg-indigo-500" style="width: 0%"></div></div>
                </div>
                <div class="card p-4 h-[300px]" id="chart-hist"></div>
                <div class="card p-4 flex-1" id="chart-scatter"></div>
            </div>

            <!-- 右侧 AI -->
            <div class="col-span-3 flex flex-col gap-4">
                <div class="card p-4 h-[200px]" id="chart-radar"></div>
                <div class="card flex-1 flex flex-col overflow-hidden">
                    <div class="p-3 border-b bg-slate-50 flex justify-between items-center">
                        <span class="font-bold text-slate-700 text-sm">智能诊断</span>
                        <button onclick="runAI()" id="btn-ai" class="text-xs bg-white border px-2 py-1 rounded">分析</button>
                    </div>
                    <div id="ai-content" class="p-4 overflow-y-auto custom-scroll text-sm text-slate-600">等待指令...</div>
                </div>
            </div>
        </main>
        
        <!-- 聊天组件 -->
        <div id="chat-wrapper">
            <div id="chat-window">
                <div class="bg-slate-800 text-white p-3 flex justify-between"><span class="text-xs font-bold">AI 助手</span><button onclick="toggleChat()"><i class="fa-solid fa-times"></i></button></div>
                <div id="chat-body" class="flex-1 bg-slate-50 p-4 overflow-y-auto custom-scroll"></div>
                <div class="p-3 bg-white border-t flex gap-2">
                    <input type="text" id="chat-input" class="flex-1 bg-slate-100 border-none rounded px-3 text-sm" placeholder="Ask AI...">
                    <button onclick="sendChat()" class="bg-blue-600 text-white rounded px-3"><i class="fa-solid fa-paper-plane"></i></button>
                </div>
            </div>
            <div class="fab-btn" onclick="toggleChat()"><i class="fa-solid fa-message"></i></div>
        </div>

        <script>
            // 核心修复：移除了 URL 中的 []()
            const injectedData = [[DATA_INSERT]];
            const DEEPSEEK_KEY = "[[SILICONFLOW_KEY]]";
            const API_URL = "https://api.siliconflow.cn/v1/chat/completions"; 
            
            let baseData = [];
            let state = { count: 0, optAge: 32 };
            let charts = {};

            function init() {
                if (injectedData && Array.isArray(injectedData)) {
                    baseData = injectedData;
                    
                    charts.hist = echarts.init(document.getElementById('chart-hist'));
                    charts.scatter = echarts.init(document.getElementById('chart-scatter'));
                    charts.radar = echarts.init(document.getElementById('chart-radar'));
                    window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()));

                    document.getElementById('in-count').addEventListener('input', (e) => {
                        state.count = parseInt(e.target.value);
                        document.getElementById('val-count').innerText = state.count;
                        update();
                    });
                    document.getElementById('opt-age').addEventListener('input', (e) => {
                        state.optAge = parseInt(e.target.value);
                        document.getElementById('val-age').innerText = state.optAge;
                        update();
                    });

                    update();
                }
            }

            function calc() {
                // 模拟简单计算逻辑
                let current = [...baseData];
                // 增加模拟数据
                for(let i=0; i<state.count; i++) current.push({age: 26, titleLevel: 2, edu: 2, isSim: true});
                
                const avgAge = current.reduce((a,b)=>a+b.age,0) / current.length || 0;
                const score = Math.max(0, 100 - Math.abs(avgAge - state.optAge) * 5).toFixed(1);
                
                return { score, current };
            }

            function update() {
                const res = calc();
                document.getElementById('tqi-score').innerText = res.score;
                document.getElementById('tqi-bar').style.width = res.score + '%';

                // Hist
                const bins = [20,30,40,50,60];
                const data = bins.map(b => res.current.filter(d => d.age >= b && d.age < b+10).length);
                charts.hist.setOption({
                    title: { text: '年龄分布', textStyle: {fontSize: 12} },
                    tooltip: {}, xAxis: { data: ['20-30','30-40','40-50','50-60','60+'] }, yAxis: {},
                    series: [{ type: 'bar', data: data, itemStyle: {color: '#3b82f6'} }]
                });

                // Scatter
                charts.scatter.setOption({
                    title: { text: '职称-年龄分布', textStyle: {fontSize: 12} },
                    xAxis: { min: 20, max: 65, name: '年龄' }, yAxis: { min: 0, max: 6, name: '职级' },
                    series: [{ 
                        type: 'scatter', 
                        data: res.current.map(d => [d.age, d.titleLevel + (Math.random()*0.4-0.2)]),
                        itemStyle: { color: d => d.data.isSim ? '#10b981' : '#6366f1' }
                    }]
                });

                // Radar
                charts.radar.setOption({
                    radar: { indicator: [{name:'结构'},{name:'学历'},{name:'职称'}] },
                    series: [{ type: 'radar', data: [{value: [80, 70, res.score], name: '当前状态'}] }]
                });
            }

            async function runAI() {
                const btn = document.getElementById('btn-ai');
                const out = document.getElementById('ai-content');
                btn.innerHTML = '...'; btn.disabled = true;
                
                const prompt = "请根据当前 TQI 指数 " + document.getElementById('tqi-score').innerText + " 给出简短评价。";
                
                try {
                    const resp = await fetch(API_URL, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + DEEPSEEK_KEY
                        },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-V3",
                            messages: [{role: "user", content: prompt}],
                            max_tokens: 500
                        })
                    });
                    const data = await resp.json();
                    if(data.error) throw new Error(data.error.message);
                    out.innerText = data.choices[0].message.content;
                } catch(e) {
                    out.innerText = "分析失败: " + e.message;
                }
                btn.innerHTML = '分析'; btn.disabled = false;
            }

            function toggleChat() {
                const w = document.getElementById('chat-window');
                w.style.display = w.style.display === 'flex' ? 'none' : 'flex';
            }
            
            async function sendChat() {
                const inp = document.getElementById('chat-input');
                const val = inp.value;
                if(!val) return;
                
                const body = document.getElementById('chat-body');
                body.innerHTML += `<div class="chat-bubble user">${val}</div>`;
                inp.value = '';
                
                // 简单回显，需自行实现完整聊天上下文
                try {
                     const resp = await fetch(API_URL, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + DEEPSEEK_KEY},
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-V3",
                            messages: [{role: "user", content: val}],
                            max_tokens: 200
                        })
                    });
                    const data = await resp.json();
                    body.innerHTML += `<div class="chat-bubble ai">${data.choices[0].message.content}</div>`;
                } catch(e) {
                    body.innerHTML += `<div class="chat-bubble ai text-red-500">Error: ${e.message}</div>`;
                }
            }

            function setMode(m) {
                document.getElementById('mode-a').className = m==='A'?'tab-btn tab-active':'tab-btn tab-inactive';
                document.getElementById('mode-b').className = m==='B'?'tab-btn tab-active':'tab-btn tab-inactive';
            }

            init();
        </script>
    </body>
    </html>
    """
    
    html_content = html_template.replace("[[SILICONFLOW_KEY]]", API_KEY)
    html_content = html_content.replace("[[DATA_INSERT]]", st.session_state.final_json_str)
    
    components.html(html_content, height=900, scrolling=False)
