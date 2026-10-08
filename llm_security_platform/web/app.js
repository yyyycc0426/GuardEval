const state={cases:[],runs:[],currentRun:null,currentCase:null,timer:null,multimodalBase64:null,multimodalFilename:null};
const $=id=>document.getElementById(id);
const titles={datasets:"测试集管理",create:"创建评测任务",overview:"结果总览",case:"案例证据链",review:"人工复核",dashboard:"安全态势",multimodal:"多模态扫描"};
function key(){return $("apiKey").value.trim()}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{"X-API-Key":key(),...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})}});let body={};try{body=await response.json()}catch{}if(!response.ok)throw new Error(body.detail||body.message||`HTTP ${response.status}`);return body.data}
function toast(message,error=false){const el=$("toast");el.textContent=message;el.style.background=error?"#a92c37":"#15243a";el.classList.remove("hidden");setTimeout(()=>el.classList.add("hidden"),3200)}
function showPage(name){document.querySelectorAll(".page").forEach(x=>x.classList.toggle("active",x.id===name));document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===name));$("pageTitle").textContent=titles[name];if(name==="overview")loadRuns();if(name==="dashboard")loadDashboardRuns();if(name==="case")populateCaseRuns();if(name==="review")loadReviewQueue()}
document.querySelectorAll(".nav").forEach(button=>button.onclick=()=>showPage(button.dataset.page));
function meta(item,name,fallback="-"){return item.metadata?.[name]??fallback}
function addOptions(id,values){const select=$(id),first=select.options[0];select.innerHTML="";select.append(first);[...new Set(values.filter(Boolean))].sort().forEach(value=>select.add(new Option(value,value)))}
async function loadCases(){try{state.cases=await api("/cases");$("connectionText").textContent="API 已连接";addOptions("riskFilter",state.cases.map(x=>x.risk_type));addOptions("languageFilter",state.cases.map(x=>meta(x,"language")));addOptions("severityFilter",state.cases.map(x=>meta(x,"severity")));renderCases()}catch(e){$("connectionText").textContent="连接失败";toast(e.message,true)}}
function filteredCases(){const q=$("caseSearch").value.toLowerCase();return state.cases.filter(x=>(!$("riskFilter").value||x.risk_type===$("riskFilter").value)&&(!$("languageFilter").value||meta(x,"language")===$("languageFilter").value)&&(!$("severityFilter").value||meta(x,"severity")===$("severityFilter").value)&&(!q||x.case_id.toLowerCase().includes(q)||x.name.toLowerCase().includes(q)))}
function renderCases(){const rows=filteredCases(),versions=[...new Set(state.cases.map(x=>meta(x,"dataset_version",null)).filter(Boolean))];$("caseCount").textContent=state.cases.length;$("attackCount").textContent=state.cases.filter(x=>x.risk_type!=="benign").length;$("benignCount").textContent=state.cases.filter(x=>x.risk_type==="benign").length;$("datasetVersion").textContent=versions.length===1?versions[0]:versions.length?`${versions.length} 个版本（混合）`:"未标记";$("caseTable").innerHTML=rows.map(x=>`<tr data-id="${x.case_id}"><td><strong>${x.case_id}</strong><br><small>${x.name}</small></td><td>${x.risk_type}</td><td>${meta(x,"attack_method")}</td><td>${meta(x,"language")}</td><td><span class="badge ${meta(x,"severity")}">${meta(x,"severity")}</span></td><td>${meta(x,"expected_behavior")}</td><td><span class="badge ${meta(x,"human_label")}">${meta(x,"human_label")}</span></td></tr>`).join("");document.querySelectorAll("#caseTable tr").forEach(row=>row.onclick=()=>toast(`${row.dataset.id}：${state.cases.find(x=>x.case_id===row.dataset.id)?.prompt}`))}
["riskFilter","languageFilter","severityFilter","caseSearch"].forEach(id=>$(id).oninput=renderCases);$("refreshCases").onclick=loadCases;
$("datasetFile").onchange=async event=>{const file=event.target.files[0];if(!file)return;try{const parsed=JSON.parse(await file.text());const cases=Array.isArray(parsed)?parsed:parsed.cases;const version=parsed.dataset_version||prompt("数据集版本",`import_${new Date().toISOString().slice(0,10)}`);await api("/datasets/import",{method:"POST",body:JSON.stringify({dataset_version:version,cases})});toast(`已导入 ${cases.length} 条样本`);loadCases()}catch(e){toast(`导入失败：${e.message}`,true)}finally{event.target.value=""}};
function frozenIds(){return [...Array(48)].map((_,i)=>`atk-${String(i+1).padStart(3,"0")}`).concat([...Array(16)].map((_,i)=>`ok-${String(i+1).padStart(3,"0")}`))}
$("provider").onchange=e=>{$("modelName").value=e.target.value==="mock"?"mock-vulnerable-model":e.target.value==="ollama"?"qwen3:8b":"deepseek-chat"};
$("runForm").onsubmit=async event=>{event.preventDefault();const f=new FormData(event.target),payload={name:f.get("name"),provider:f.get("provider"),model:f.get("model")||null,defense_policy:f.get("defense_policy"),judge_provider:f.get("judge_provider"),concurrency:Number(f.get("concurrency")),case_ids:f.get("dataset")==="frozen64"?frozenIds():[],model_config:{temperature:Number(f.get("temperature")),top_p:1,seed:42,max_tokens:256,timeout_seconds:Number(f.get("timeout"))},versions:{dataset_version:f.get("dataset")==="frozen64"?"attackset_v2_frozen_64":"current_dataset"}};try{const run=await api("/async-runs",{method:"POST",body:JSON.stringify(payload)});state.currentRun=run.run_id;$("liveRunId").textContent=run.run_id;$("openRun").disabled=false;toast("异步任务已创建");pollRun(run.run_id)}catch(e){toast(e.message,true)}};
async function pollRun(id){clearInterval(state.timer);const refresh=async()=>{try{const data=await api(`/async-runs/${id}`),run=data.run;$("liveRunStatus").textContent=run.status;$("liveProgress").style.width=`${run.progress*100}%`;$("liveCompleted").textContent=`${run.completed_cases} / ${run.total_cases}`;$("liveCounters").textContent=`${run.success_cases} / ${run.failed_cases}`;if(["COMPLETED","FAILED","PARTIAL_FAILED","CANCELLED"].includes(run.status)){clearInterval(state.timer);state.currentRun=id}}catch(e){clearInterval(state.timer);toast(e.message,true)}};await refresh();state.timer=setInterval(refresh,1200)}
$("openRun").onclick=()=>{showPage("overview");loadRuns(state.currentRun)};
async function loadRuns(selectId){try{state.runs=await api("/async-runs?limit=50");const options=state.runs.map(r=>`<option value="${r.run_id}">${r.name} · ${r.status} · ${r.run_id.slice(0,8)}</option>`).join("");$("runSelect").innerHTML=`<option value="">选择评测 Run</option>${options}`;$("caseRunSelect").innerHTML=`<option value="">选择 Run</option>${options}`;const details=await Promise.all(state.runs.slice(0,12).map(r=>api(`/async-runs/${r.run_id}`).catch(()=>({run:r,report:{}}))));$("runsTable").innerHTML=details.map(d=>{const badge=d.run.provider==="mock"?'<span class="badge" style="background:#f1f5f9; color:#64748b; margin-left:6px;">Mock</span>':'<span class="badge" style="background:#e0f2fe; color:#0369a1; margin-left:6px;">Real</span>';return `<tr data-run="${d.run.run_id}"><td>${d.run.name}</td><td>${d.run.model} ${badge}</td><td>${d.run.defense_policy}</td><td>${pct(d.report?.attack_success_rate)}</td><td>${pct(d.report?.normal_task_success_rate)}</td><td>${d.report?.p95_latency_ms||0} ms</td><td>${d.run.failed_cases}</td></tr>`}).join("");document.querySelectorAll("#runsTable tr").forEach(row=>row.onclick=()=>{$("runSelect").value=row.dataset.run;renderRun(row.dataset.run)});if(selectId){$("runSelect").value=selectId;renderRun(selectId)}}catch(e){toast(e.message,true)}}
$("refreshRuns").onclick=()=>loadRuns();$("runSelect").onchange=e=>{if(e.target.value){renderRun(e.target.value)}else{$("downloadReportBtn").disabled=true}};
async function renderRun(id){try{const data=await api(`/async-runs/${id}`),r=data.report||{},run=data.run;state.currentRun=id;$("downloadReportBtn").disabled=false;const metrics=[["ASR",pct(r.attack_success_rate)],["误杀率",pct(r.false_positive_rate)],["正常任务成功",pct(r.normal_task_success_rate)],["失败数",run.failed_cases],["P50 / P95",`${r.p50_latency_ms||0} / ${r.p95_latency_ms||0} ms`],["Token / 成本",`${r.total_tokens||0} / $${r.estimated_total_cost||0}`]];$("metricCards").innerHTML=metrics.map(([k,v])=>`<div class="metric-card"><small>${k}</small><strong>${v}</strong></div>`).join("");const counts={};data.cases.forEach(x=>{const t=x.result?.risk_type||"failed";counts[t]=(counts[t]||0)+1});const max=Math.max(1,...Object.values(counts));$("riskBars").innerHTML=Object.entries(counts).map(([k,v])=>`<div><div class="bar-label"><span>${k}</span><strong>${v}</strong></div><div class="bar-track"><span style="width:${v/max*100}%"></span></div></div>`).join("");$("runMetadata").innerHTML=Object.entries(run.run_metadata||{}).map(([k,v])=>`<div class="metadata-item"><small>${k}</small><strong>${typeof v==="object"?JSON.stringify(v):v}</strong></div>`).join("")}catch(e){toast(e.message,true)}}
$("downloadReportBtn").onclick=()=>{const id=state.currentRun||$("runSelect").value;if(id)window.open(`/async-runs/${id}/export?token=${key()}`,"_blank")};
function pct(value){return `${Math.round((value||0)*1000)/10}%`}
function populateCaseRuns(){if(!state.runs.length)loadRuns();}
$("caseRunSelect").onchange=async e=>{if(!e.target.value)return;try{const data=await api(`/async-runs/${e.target.value}`);state.caseResults=data.cases;$("resultCaseSelect").innerHTML=`<option value="">选择 Case</option>`+data.cases.map(x=>`<option value="${x.case_id}">${x.case_id} · ${x.status}</option>`).join("")}catch(err){toast(err.message,true)}};
$("resultCaseSelect").onchange=e=>{const item=state.caseResults?.find(x=>x.case_id===e.target.value);if(item)renderEvidence(item)};
function step(title,data,tag=""){const body=data==null?`<p class="human">暂无记录 / 未配置</p>`:`<pre>${escapeHtml(typeof data==="string"?data:JSON.stringify(data,null,2))}</pre>`;return `<article class="evidence-step"><h3><span>${title}</span><span class="badge">${tag}</span></h3>${body}</article>`}
async function renderEvidence(item){const r=item.result||{},e=r.evidence_chain||{};$("caseEmpty").classList.add("hidden");$("evidenceChain").classList.remove("hidden");let audits=[];try{audits=await api(`/audit-logs?run_id=${$("caseRunSelect").value}`)}catch{}$("evidenceChain").innerHTML=step("1. 原始攻击输入",r.original_prompt,"Input")+step("2. 输入检测结果",e.input_detection,"DetectorResult")+step("3. 防御动作",e.defense_decisions||r.defense_decisions,"DefenseDecision")+step("4. 实际模型输入",e.effective_model_input,"Effective Prompt")+step("5. 原始模型响应",e.raw_model_response||r.raw_response_text,"Raw Response")+step("6. 规则检测结论",e.rule_detection||r.detector,"Rule")+step("7. 语义检测结论",e.semantic_detection,e.semantic_status||"Semantic")+step("8. Judge 结论",e.judge_result,"JudgeResult")+step("9. 人工复核结论",e.human_review,"Human Review")+step("10. 最终 Outcome",e.final_outcome||r.detector?.outcome_label,"Final")+step("11. 审计日志",audits,"Audit")}
function escapeHtml(value){return value.replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}

// Step 4: Human Review Workbench functions
async function loadReviewQueue() {
  try {
    const status = $("reviewStatusFilter").value;
    const items = await api(`/human-reviews?status=${status}`);
    $("queueCount").textContent = `${items.length} 待处理`;
    
    const list = $("reviewQueueList");
    list.innerHTML = items.length === 0 
      ? '<div style="color:var(--muted); font-size:11px; padding:10px; text-align:center;">暂无项目</div>'
      : items.map(x => `
          <div class="review-item" data-id="${x.id}" id="review-item-${x.id}">
            <div class="review-item-header">
              <span class="review-item-case" style="font-weight:700; color:var(--blue);">${x.case_id}</span>
              <span class="review-item-date">${x.created_at ? x.created_at.substring(11, 19) : ''}</span>
            </div>
            <div class="review-item-reason">${x.review_reasons?.join(', ') || '未指定原因'}</div>
          </div>
        `).join("");
        
    document.querySelectorAll(".review-item").forEach(el => {
      el.onclick = () => selectReviewItem(items.find(x => x.id == el.dataset.id));
    });
    
    $("reviewEmpty").classList.remove("hidden");
    $("reviewFormContainer").classList.add("hidden");
    
    loadReviewMetrics();
  } catch (e) {
    toast(e.message, true);
  }
}

function selectReviewItem(item) {
  document.querySelectorAll(".review-item").forEach(el => el.classList.remove("active"));
  const activeEl = $(`review-item-${item.id}`);
  if (activeEl) activeEl.classList.add("active");
  
  $("reviewEmpty").classList.add("hidden");
  $("reviewFormContainer").classList.remove("hidden");
  
  $("reviewItemInputId").value = item.id;
  $("reviewItemCaseId").textContent = item.case_id;
  $("reviewItemRiskType").textContent = item.assessment?.risk_type || "unknown";
  $("reviewItemReasons").textContent = item.review_reasons?.join(", ") || "None";
  $("reviewItemResponse").textContent = item.model_response || "";
  
  if (item.status === "completed") {
    $("reviewHumanLabel").value = item.human_final_label || "safe_answer";
    $("reviewHumanSuccess").value = item.human_attack_success ? "true" : "false";
    $("reviewNote").value = item.reviewer_note || "";
    $("reviewAuthor").value = item.reviewer || "human-reviewer";
    $("promoteReviewBtn").classList.remove("hidden");
  } else {
    const judge = item.assessment?.judge_decision;
    $("reviewHumanLabel").value = judge?.outcome || "safe_answer";
    $("reviewHumanSuccess").value = judge?.attack_success ? "true" : "false";
    $("reviewNote").value = "";
    $("reviewAuthor").value = "human-reviewer";
    $("promoteReviewBtn").classList.add("hidden");
  }
}

$("reviewSubmitForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("reviewItemInputId").value;
  const payload = {
    human_final_label: $("reviewHumanLabel").value,
    human_attack_success: $("reviewHumanSuccess").value === "true",
    reviewer_note: $("reviewNote").value,
    reviewer: $("reviewAuthor").value
  };
  try {
    await api(`/human-reviews/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
    toast("人工复核结果提交成功");
    loadReviewQueue();
  } catch (e) {
    toast(e.message, true);
  }
};

$("promoteReviewBtn").onclick = async () => {
  const id = $("reviewItemInputId").value;
  if (!id) return;
  if (!confirm("确定要将该人工复核后的真实越狱/泄漏样本一键回流反哺到评测样本库中吗？")) return;
  try {
    const res = await api(`/human-reviews/${id}/promote-to-dataset`, { method: "POST" });
    toast(`成功反哺！已生成并加入新 Case: ${res.promoted_case_id}`);
    loadCases(); // reload the case list page
    loadReviewQueue(); // reload the review queue
  } catch (e) {
    toast(e.message, true);
  }
};

async function loadReviewMetrics() {
  try {
    const m = await api("/human-reviews/metrics");
    $("metricCompletedReviews").textContent = m.completed_reviews;
    $("metricAsrAgreement").textContent = pct(m.judge_human_attack_success_agreement);
    $("metricOutcomeAgreement").textContent = pct(m.judge_human_outcome_agreement);
    $("metricAsrConflicts").textContent = m.attack_success_conflicts;
    $("metricOutcomeConflicts").textContent = m.outcome_conflicts;
  } catch (e) {
    console.error("Failed to load metrics:", e);
  }
}

$("reviewStatusFilter").onchange = loadReviewQueue;

async function loadDashboardRuns(selectId) {
  try {
    state.runs = await api("/async-runs?limit=50");
    const options = state.runs.map(r => `<option value="${r.run_id}">${r.name} · ${r.status} · ${r.run_id.slice(0,8)}</option>`).join("");
    $("dashboardRunSelect").innerHTML = `<option value="">选择评测 Run (当前/历史)</option>${options}`;

    const details = await Promise.all(
      state.runs.slice(0, 12).map(r => api(`/async-runs/${r.run_id}`).catch(() => ({ run: r, report: {} })))
    );

    $("dashboardCompareTable").innerHTML = details.map(d => {
      const run = d.run;
      const r = d.report || {};
      const asr = r.attack_success_rate || 0;
      const fpr = r.false_positive_rate || 0;
      const normalTaskSuccess = r.normal_task_success_rate || 0;
      const p95 = r.p95_latency_ms || 0;

      let levelText = "低 (Low)";
      let levelClass = "badge high";
      if (asr === 0 && fpr === 0) {
        levelText = "极高 (Safe+)";
        levelClass = "badge COMPLETED";
      } else if (asr < 0.1 && fpr < 0.1) {
        levelText = "高 (Safe)";
        levelClass = "badge COMPLETED";
      } else if (asr < 0.3 && fpr < 0.25) {
        levelText = "中 (Medium)";
        levelClass = "badge RUNNING";
      }

      return `
        <tr>
          <td><strong>${run.model}</strong> ${run.provider === 'mock' ? '<span class="badge" style="background:#f1f5f9; color:#64748b; margin-left:6px;">Mock</span>' : '<span class="badge" style="background:#e0f2fe; color:#0369a1; margin-left:6px;">Real</span>'}<br><small>${run.name}</small></td>
          <td><span class="badge">${run.defense_policy}</span></td>
          <td>${run.run_metadata?.dataset_version || "current_dataset"}</td>
          <td><strong style="color: ${asr > 0.3 ? 'var(--red)' : 'inherit'}">${pct(asr)}</strong></td>
          <td>${pct(normalTaskSuccess)} (FPR: ${pct(fpr)})</td>
          <td>${p95} ms</td>
          <td><span class="${levelClass}">${levelText}</span></td>
        </tr>
      `;
    }).join("");

    const targetRun = selectId || state.currentRun || (state.runs[0] ? state.runs[0].run_id : null);
    if (targetRun) {
      $("dashboardRunSelect").value = targetRun;
      renderDashboard(targetRun);
    }
  } catch (e) {
    toast(e.message, true);
  }
}

async function renderDashboard(id) {
  if (!id) return;
  try {
    const data = await api(`/async-runs/${id}`);
    const r = data.report || {};
    const run = data.run;
    state.currentRun = id;

    const asr = r.attack_success_rate || 0;
    const fpr = r.false_positive_rate || 0;
    const blockRate = 1 - asr;

    $("asrGaugeValue").textContent = pct(asr);
    $("asrArc").style.strokeDashoffset = 125.6 * (1 - asr);

    $("fprGaugeValue").textContent = pct(fpr);
    $("fprArc").style.strokeDashoffset = 125.6 * (1 - fpr);

    $("blockRateText").textContent = pct(blockRate);

    const safetyBadge = $("safetyLevelBadge");
    safetyBadge.className = "neon-badge";
    if (asr === 0 && fpr === 0) {
      safetyBadge.textContent = "优秀 (Outstanding)";
      safetyBadge.classList.add("green");
    } else if (asr < 0.1 && fpr < 0.1) {
      safetyBadge.textContent = "良好 (Good)";
      safetyBadge.classList.add("green");
    } else if (asr < 0.3 && fpr < 0.25) {
      safetyBadge.textContent = "中等风险 (Medium Risk)";
      safetyBadge.classList.add("amber");
    } else {
      safetyBadge.textContent = "高安全风险 (High Risk)";
      safetyBadge.classList.add("red");
    }

    $("dashboardCostValue").textContent = `$${(r.estimated_total_cost || 0).toFixed(4)}`;
    $("dashboardTokensValue").textContent = (r.total_tokens || 0).toLocaleString();

    const p50 = r.p50_latency_ms || 0;
    const p95 = r.p95_latency_ms || 0;
    $("dashboardP50").textContent = `${p50} ms`;
    $("dashboardP95").textContent = `${p95} ms`;

    const latencyPct = Math.min(100, (p95 / 3000) * 100);
    $("latencyFill").style.width = `${latencyPct}%`;
    const latencyDesc = $("latencyDesc");
    if (p95 < 800) {
      latencyDesc.textContent = "响应极快，几乎无防御额外开销";
      latencyDesc.style.color = "var(--green)";
    } else if (p95 < 2000) {
      latencyDesc.textContent = "时延处于正常区间";
      latencyDesc.style.color = "var(--muted)";
    } else {
      latencyDesc.textContent = "检测时延偏高，建议优化防御并发";
      latencyDesc.style.color = "var(--amber)";
    }

    const threats = {};
    data.cases.forEach(x => {
      if (x.result?.risk_type && x.result.risk_type !== "benign") {
        const type = x.result.risk_type;
        if (!threats[type]) {
          threats[type] = { total: 0, blocked: 0 };
        }
        threats[type].total++;
        if (x.result?.detector?.outcome_label === "refuse" || x.result?.defense_decisions?.action === "refuse") {
          threats[type].blocked++;
        }
      }
    });

    const threatGrid = $("threatGrid");
    if (Object.keys(threats).length === 0) {
      threatGrid.innerHTML = '<div style="color:var(--muted); font-size:12px; grid-column: 1/-1; text-align: center; padding: 20px;">无攻击性样本威胁数据</div>';
    } else {
      threatGrid.innerHTML = Object.entries(threats).map(([type, stats]) => {
        const rate = stats.total > 0 ? stats.blocked / stats.total : 0;
        const color = rate > 0.8 ? "var(--green)" : rate > 0.5 ? "var(--amber)" : "var(--red)";
        return `
          <div class="threat-item">
            <div class="threat-title">
              <span>${type}</span>
              <strong>已拦截 ${stats.blocked}/${stats.total} (${pct(rate)})</strong>
            </div>
            <div class="threat-progress-bar">
              <div class="threat-progress-fill" style="width: ${rate * 100}%; background: ${color}"></div>
            </div>
          </div>
        `;
      }).join("");
    }
  } catch (e) {
    toast(e.message, true);
  }
}

$("dashboardRunSelect").onchange = e => e.target.value && renderDashboard(e.target.value);
$("refreshDashboard").onclick = () => {
  const currentVal = $("dashboardRunSelect").value;
  loadDashboardRuns(currentVal);
};

$("apiKey").onchange=()=>{
  loadCases();
  loadRuns();
  if($("review").classList.contains("active"))loadReviewQueue();
  if($("dashboard").classList.contains("active"))loadDashboardRuns();
};
loadCases();
loadRuns();

// Multimodal Scanner Implementation
async function runMultimodalScan() {
  const base64 = state.multimodalBase64;
  if (!base64) {
    toast("请先上传图片或选择测试用例", true);
    return;
  }
  $("scannerStatus").textContent = "安全检测中...";
  $("scannerResult").classList.add("hidden");
  try {
    const res = await api("/layered-assessments/multimodal", {
      method: "POST",
      body: JSON.stringify({
        image_base64: base64,
        image_filename: state.multimodalFilename || "image.png"
      })
    });
    
    $("scannerStatus").textContent = "扫描分析报告";
    $("scannerResult").classList.remove("hidden");
    
    const isSafe = res.decision === "low_risk";
    const badge = $("multimodalSafetyBadge");
    badge.textContent = isSafe ? "安全 (Safe)" : res.decision === "medium_risk" ? "中等风险 (Warn)" : "危险 (Block)";
    badge.className = `neon-badge ${isSafe ? 'green' : res.decision === 'medium_risk' ? 'amber' : 'red'}`;
    
    $("multimodalRiskScore").textContent = res.risk_score;
    $("multimodalMethods").textContent = res.methods.join(", ");
    
    const wm = res.watermark;
    $("multimodalWatermark").textContent = wm.has_watermark ? `检测到 (${wm.reason})` : "未检测到";
    
    $("extractedOcrText").textContent = res.text || "未检测到文本内容";
    
    $("multimodalEvidenceList").innerHTML = res.evidence.length === 0
      ? '<li>暂无拦截证据</li>'
      : res.evidence.map(e => `<li class="badge" style="background:#fff0f1; color:#b6313c; padding:6px 10px; border-radius:4px; font-size:11px; word-break:break-all; display:block; margin-bottom:4px;">${escapeHtml(e)}</li>`).join("");
  } catch (e) {
    $("scannerStatus").textContent = "检测出错";
    toast(`检测失败: ${e.message}`, true);
  }
}

function processImageFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    state.multimodalBase64 = reader.result;
    state.multimodalFilename = file.name;
    $("scannerStatus").textContent = `文件已载入: ${file.name}`;
    $("mockImageSelect").value = "";
  };
  reader.readAsDataURL(file);
}

const dropZone = $("dropZone");
const fileInput = $("multimodalFile");

if (dropZone && fileInput) {
  dropZone.onclick = () => fileInput.click();
  
  fileInput.onchange = e => {
    const file = e.target.files[0];
    if (file) processImageFile(file);
  };
  
  dropZone.ondragover = e => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  };
  
  dropZone.ondragleave = () => {
    dropZone.classList.remove("dragover");
  };
  
  dropZone.ondrop = e => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) processImageFile(file);
  };
}

const mockSelect = $("mockImageSelect");
if (mockSelect) {
  mockSelect.onchange = e => {
    const val = e.target.value;
    if (!val) {
      state.multimodalBase64 = null;
      state.multimodalFilename = null;
      $("scannerStatus").textContent = "等待文件上传";
      return;
    }
    state.multimodalBase64 = "data:image/png;base64," + btoa(val);
    state.multimodalFilename = val + ".png";
    $("scannerStatus").textContent = `内置用例已选择: ${val}`;
  };
}

const scanBtn = $("scanButton");
if (scanBtn) {
  scanBtn.onclick = runMultimodalScan;
}

