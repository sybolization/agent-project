/* ============================================================
   Agent 执行流程可视化 -- 应用逻辑
   ============================================================ */

// ---------- 全局状态 ----------
const state = {
  events: [],            // 已解析的事件数组
  timeline: null,        // 时间线数据结构 (buildTimeline 产出)
  currentIndex: 0,       // 当前播放/选中位置
  isPlaying: false,      // 是否正在播放
  speed: 1,              // 播放速度倍数
  playTimer: null,       // 播放定时器句柄
  viewMode: 'global',    // 视图模式: 'global' | 'subagent'
  expandedAgentId: null, // 当前展开的 subagent ID
  selectedNodeId: null   // 当前选中的节点ID，用于持久化显示选中状态
};

// ---------- Tooltip 状态 ----------
let tooltipEl = null;
let tooltipTimer = null;
let hoveredNode = null;

// ---------- DOM 引用 ----------
const dom = {
  fileInput:      document.getElementById('fileInput'),
  dropHint:       document.getElementById('dropHint'),
  eventCount:     document.getElementById('eventCount'),
  canvas:         document.getElementById('timelineCanvas'),
  detailPanel:    document.getElementById('detailPanel'),
  btnPlay:        document.getElementById('btnPlay'),
  btnPrev:        document.getElementById('btnPrev'),
  btnNext:        document.getElementById('btnNext'),
  speedSelect:    document.getElementById('speedSelect'),
  progressBar:    document.getElementById('progressBar'),
  positionLabel:  document.getElementById('positionLabel'),
  btnClear:       document.getElementById('btnClear')
};

// ---------- Canvas 上下文 ----------
const ctx = dom.canvas.getContext('2d');

// ---------- 字体栈常量 ----------
const FONT_STACK = '"Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

// ============================================================
// JSONL 解析器
// ============================================================

/**
 * 解析 JSONL 文本，返回 { events, errors }
 * - 按行分割，过滤空行
 * - 每行尝试 JSON.parse
 * - 成功追加到 events，失败记录到 errors
 * - 解析完成后按 timestamp 排序
 *
 * @param {string} text - JSONL 原始文本
 * @returns {{ events: Array, errors: Array<{line: number, message: string}> }}
 */
function parseJSONL(text) {
  const events = [];
  const errors = [];

  const lines = text.split('\n');

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed === '') {
      continue;
    }
    try {
      const parsed = JSON.parse(trimmed);
      events.push(parsed);
    } catch (err) {
      errors.push({
        line: i + 1,
        message: err.message || String(err)
      });
    }
  }

  // 按 timestamp 排序（处理可能乱序的 JSONL 行）
  events.sort((a, b) => {
    const ta = a.timestamp || '';
    const tb = b.timestamp || '';
    if (ta < tb) return -1;
    if (ta > tb) return 1;
    return 0;
  });

  return { events, errors };
}

// ============================================================
// 时间线构建器
// ============================================================

/**
 * 根据事件数组构建时间线 DAG 结构
 * 1. 按 session_id 分组
 * 2. 识别根代理（parent_session_id 为 null 或无此字段）
 * 3. 建立父子关系
 *
 * @param {Array} events - 已解析的事件数组
 * @returns {Object} timeline 数据结构
 */
function buildTimeline(events) {
  // 1. 按 session_id 分组（过滤旧格式记录：无 event_type 且无 event_id）
  const sessionMap = {};
  let skippedCount = 0;
  for (const evt of events) {
    if (!evt.event_type && !evt.event_id) {
      skippedCount++;
      continue;
    }
    const sid = evt.session_id || 'unknown';
    if (!sessionMap[sid]) {
      sessionMap[sid] = [];
    }
    sessionMap[sid].push(evt);
  }

  // 2. 为每个 session 构建元数据节点
  const sessions = {};
  const sessionIds = Object.keys(sessionMap);

  for (const sid of sessionIds) {
    const evtList = sessionMap[sid];

    // 按 timestamp 排序确保内部顺序
    evtList.sort((a, b) => {
      const ta = a.timestamp || '';
      const tb = b.timestamp || '';
      if (ta < tb) return -1;
      if (ta > tb) return 1;
      return 0;
    });

    // 提取元数据：agent_id, parent_agent_id, parent_session_id, phase
    let agentId = 'unknown';
    let parentAgentId = null;
    let parentSessionId = null;
    let phase = null;

    // 从事件中提取元数据（取第一个非空值）
    for (const evt of evtList) {
      if (agentId === 'unknown' && evt.agent_id) {
        agentId = evt.agent_id;
      }
      if (parentAgentId === null && evt.parent_agent_id) {
        parentAgentId = evt.parent_agent_id;
      }
      if (parentSessionId === null && evt.parent_session_id) {
        parentSessionId = evt.parent_session_id;
      }
      if (phase === null && evt.phase) {
        phase = evt.phase;
      }
    }

    // 统计
    let totalIterations = 0;
    let toolCalls = 0;
    let hasError = false;

    for (const evt of evtList) {
      if (evt.iteration !== undefined && evt.iteration !== null) {
        totalIterations = Math.max(totalIterations, evt.iteration + 1);
      }
      if (evt.event_type === 'tool_call' || evt.type === 'tool_call') {
        toolCalls++;
      }
      if (evt.event_type === 'error' || evt.type === 'error' || evt.level === 'error') {
        hasError = true;
      }
    }

    sessions[sid] = {
      session_id: sid,
      agent_id: agentId,
      parent_agent_id: parentAgentId,
      parent_session_id: parentSessionId,
      phase: phase,
      events: evtList,
      children: [],
      stats: {
        totalIterations: totalIterations,
        toolCalls: toolCalls,
        hasError: hasError,
        eventCount: evtList.length
      }
    };
  }

  // 3. 建立父子关系
  let root = null;

  for (const sid of sessionIds) {
    const node = sessions[sid];
    const parentSid = node.parent_session_id;

    if (parentSid === null || parentSid === undefined) {
      // 这是根代理
      root = node;
    } else if (sessions[parentSid]) {
      // 将当前 node 加入父 session 的 children 列表（避免重复添加）
      if (!sessions[parentSid].children.includes(node)) {
        sessions[parentSid].children.push(node);
      }
    }
    // 如果 parentSid 指向的 session 不在当前数据集中，也视为根级
  }

  // 如果没找到显式的根，选择第一个没有 parent_session_id 的作为根
  if (!root) {
    for (const sid of sessionIds) {
      const node = sessions[sid];
      if (node.parent_session_id === null || node.parent_session_id === undefined) {
        root = node;
        break;
      }
    }
    // 如果仍然没有根，选择第一个 session 作为根
    if (!root && sessionIds.length > 0) {
      root = sessions[sessionIds[0]];
    }
  }

  // 4. 递归排序 children（按 timestamp）
  function sortChildren(node) {
    if (!node || !node.children) return;
    node.children.sort((a, b) => {
      const ta = (a.events.length > 0 && a.events[0].timestamp) ? a.events[0].timestamp : '';
      const tb = (b.events.length > 0 && b.events[0].timestamp) ? b.events[0].timestamp : '';
      if (ta < tb) return -1;
      if (ta > tb) return 1;
      return 0;
    });
    for (const child of node.children) {
      sortChildren(child);
    }
  }

  if (root) {
    sortChildren(root);
  }

  return {
    root: root,
    sessions: sessions,
    skippedCount: skippedCount
  };
}

// ============================================================
// Canvas 渲染 -- DAG 布局 + 多形状节点绘制
// ============================================================

// --- 节点形状/尺寸配置 ---
const NODE_CONFIG = {
  agent_started:      { shape: 'rect', w: 120, h: 36, label: '开始' },
  agent_completed:    { shape: 'rect', w: 120, h: 36, label: '结束' },
  subagent_created:   { shape: 'rect', w: 140, h: 36, label: '子代理' },
  subagent_completed: { shape: 'rect', w: 140, h: 36, label: '完成' },
  subagent_failed:    { shape: 'rect', w: 140, h: 36, label: '失败' },
  iteration_start:    { shape: 'circle', r: 6, label: '迭代' },
  iteration_end:      { shape: 'circle', r: 6, label: '迭代' },
  thinking:           { shape: 'bubble', w: 180, h: 44, label: '思考' },
  llm_call:           { shape: 'rect', w: 100, h: 32, label: 'LLM' },
  llm_response:       { shape: 'rect', w: 100, h: 32, label: 'LLM' },
  tool_call:          { shape: 'card', w: 140, h: 40, label: '工具' },
  tool_result:        { shape: 'tag', w: 130, h: 32, label: '结果' },
  phase_transition:   { shape: 'diamond', w: 28, h: 28, label: '切换' },
  state_change:       { shape: 'rect', w: 110, h: 32, label: '状态' },
  error:              { shape: 'rect', w: 150, h: 40, label: '错误' },
  spawn_agents_started:{ shape: 'rect', w: 160, h: 40, label: '派生' },
  subagent_context:   { shape: 'rect', w: 110, h: 32, label: '上下文' },
  subagent_iteration: { shape: 'circle', r: 5, label: '迭代' },
  tool_execution:     { shape: 'tag', w: 110, h: 28, label: '执行' },
  skill_loaded:       { shape: 'tag', w: 120, h: 28, label: '技能' },
  llm_error:          { shape: 'rect', w: 150, h: 40, label: 'LLM错误' },
  round:               { shape: 'round', w: 200, h: 72, label: '轮次' },
};

// --- 阶段颜色映射 ---
const PHASE_COLORS = {
  COLLECT: '#4A90D9', PLAN: '#F5A623', EXECUTE: '#7ED321',
  REPORT: '#9B59B6', DEFAULT: '#95A5A6'
};

/** 获取阶段对应颜色 */
function getPhaseColor(phase) {
  return PHASE_COLORS[phase] || PHASE_COLORS.DEFAULT;
}

function groupEvents(events) {
  const grouped = [];
  let i = 0;

  while (i < events.length) {
    const evt = events[i];

    // 跳过 iteration_start / iteration_end 节点，不显示
    if (evt.event_type === 'iteration_start' || evt.event_type === 'iteration_end') {
      i++;
      continue;
    }

    if (evt.event_type === 'llm_call') {
      const round = {
        type: 'round',
        event: evt,
        llmData: evt.data || {},
        tools: [],
        hasTools: false,
      };
      i++;

      while (i < events.length) {
        const next = events[i];
        // 跳过 iteration_start / iteration_end
        if (next.event_type === 'iteration_start' || next.event_type === 'iteration_end') {
          i++;
          continue;
        }
        if (next.event_type === 'tool_call') {
          const callEvt = next;
          i++;
          let resultEvt = null;
          if (i < events.length && events[i].event_type === 'tool_result') {
            resultEvt = events[i];
            i++;
          }
          round.tools.push({ call: callEvt, result: resultEvt });
          round.hasTools = true;
        } else if (
          next.event_type === 'llm_response' ||
          next.event_type === 'thinking' ||
          next.event_type === 'agent_completed' ||
          next.event_type === 'agent_started'
        ) {
          break;
        } else if (next.event_type === 'skill_loaded') {
          grouped.push({ type: 'skill_loaded', event: next });
          i++;
        } else {
          break;
        }
      }

      grouped.push(round);
    } else if (evt.event_type === 'llm_response') {
      grouped.push({
        type: 'round',
        event: evt,
        llmData: evt.data || {},
        tools: [],
        hasTools: false,
      });
      i++;
    } else {
      grouped.push({ type: evt.event_type, event: evt });
      i++;
    }
  }

  return grouped;
}

/** 获取事件摘要 */
function getEventSummary(node) {
  const { type, event: evt } = node;
  const data = evt.data || {};

  switch (type) {
    case 'tool_call':
      return (data.tool_name || '工具').substring(0, 14);
    case 'tool_result': {
      const hasSuccess = data.success === true;
      const hasError = data.success === false || (data.error && data.error.length > 0);
      const isErrorType = (data.result_type || '').indexOf('error') >= 0;
      const ok = hasSuccess ? '✓' : (hasError || isErrorType ? '✗' : '');
      const detail = data.error ? String(data.error).substring(0, 8)
                     : (data.result_type || '').replace(/_/g, ' ').substring(0, 10);
      return (ok + (detail ? ' ' + detail : '')).substring(0, 16);
    }
    case 'tool_execution': {
      const name = data.tool_name || '';
      const shortName = name.split('/').pop().split(':').shift() || name;
      const prefix = data.success === true ? '✓' : (data.success === false ? '✗' : '▸');
      const resultType = data.result_type || '';
      if (shortName && resultType) {
        return `${prefix} ${shortName}·${resultType}`.substring(0, 16);
      }
      if (shortName) return `${prefix} ${shortName}`.substring(0, 14);
      if (resultType) return `${prefix} ${resultType}`.substring(0, 14);
      return prefix + ' 执行';
    }
    case 'thinking':
      return (data.content || '思考中...').substring(0, 20);
    case 'llm_call':
      if (data.timing_ms) {
        const sec = (data.timing_ms / 1000).toFixed(1);
        return `${sec}s`;
      }
      return 'LLM';
    case 'llm_response':
      return (data.content || '回复').substring(0, 15);
    case 'phase_transition':
      return '→ ' + (data.to_phase || '').substring(0, 10);
    case 'error':
    case 'llm_error':
      return (data.message || '错误').substring(0, 15);
    case 'agent_started':
      return '开始';
    case 'agent_completed':
      return '完成';
    case 'subagent_created':
      return '子代理';
    case 'subagent_completed':
      return '完成';
    case 'subagent_failed':
      return '失败';
    case 'iteration_start':
    case 'iteration_end':
      return '迭代';
    case 'spawn_agents_started':
      return '派生';
    case 'skill_loaded':
      return (data.skill_name || '技能').split('/').pop().substring(0, 12);
    case 'round':
      return '';
    default:
      return (NODE_CONFIG[type]?.label || type || 'unknown').replace(/_/g, ' ');
  }
}

/** 颜色变亮工具函数 */
function lightenColor(hex, factor) {
  hex = hex.replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  const lr = Math.min(255, Math.round(r + (255 - r) * factor));
  const lg = Math.min(255, Math.round(g + (255 - g) * factor));
  const lb = Math.min(255, Math.round(b + (255 - b) * factor));
  return `rgb(${lr},${lg},${lb})`;
}

/**
 * 通用文本截断工具函数
 * 根据画布上下文和最大宽度智能截断文本，超出部分显示省略号
 * @param {CanvasRenderingContext2D} ctx - 画布渲染上下文
 * @param {string} text - 原始文本
 * @param {number} maxWidth - 最大允许宽度（像素）
 * @param {number} [maxLength=100] - 最大字符长度限制
 * @returns {string} 截断后的文本（可能带省略号）
 */
function truncateTextToFit(ctx, text, maxWidth, maxLength) {
  if (!text) return '';
  let displayText = String(text).substring(0, maxLength || 100);
  while (ctx.measureText(displayText).width > maxWidth && displayText.length > 0) {
    displayText = displayText.slice(0, -1);
  }
  if (displayText.length < text.length && displayText.length > 0) {
    // 移除最后一个字符以容纳省略号
    while (ctx.measureText(displayText + '...').width > maxWidth && displayText.length > 0) {
      displayText = displayText.slice(0, -1);
    }
    return displayText + '...';
  }
  return displayText;
}

/** 绘制纯色深灰背景 */
function drawSolidBackground(width, height) {
  ctx.fillStyle = '#606060';
  ctx.fillRect(0, 0, width, height);
}

/** 圆角矩形路径 */
function roundedRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

// ============================================================
// DAG 布局算法
// ============================================================

/**
 * 递归计算 DAG 中每个节点的 (x, y) 坐标
 * @param {Object} timeline - buildTimeline 产出
 * @param {number} canvasWidth - 画布宽度
 * @returns {{ allNodes: Array, sessionRows: Object }}
 */
function computeLayout(timeline, canvasWidth) {
  const NODE_GAP_X = 20;
  const ROW_GAP_Y = 90;
  const MARGIN_X = 40;
  const MARGIN_Y = 30;
  const MAX_ROW_WIDTH = canvasWidth - MARGIN_X * 2;
  const INTRA_ROW_GAP = Math.round(ROW_GAP_Y * 0.55);

  const allNodes = [];
  const sessionRows = {};

  function layoutSession(sessionNode, startX, startY) {
    const rawEvents = sessionNode.events || [];
    const events = groupEvents(rawEvents);
    const sid = sessionNode.session_id;
    let x = startX;
    let y = startY;
    let maxRowHeight = 0;
    const rowNodes = [];

    for (const gEvt of events) {
      const evtType = gEvt.type;
      const evt = gEvt.event;

      let w, h, cfg;

      if (evtType === 'round') {
        const toolCount = (gEvt.tools || []).length;
        w = Math.max(160, 80 + toolCount * 84);
        h = 72;
        cfg = NODE_CONFIG['round'] || { shape: 'round', w: w, h: h, label: '轮次' };
      } else {
        cfg = NODE_CONFIG[evtType] || { shape: 'rect', w: 100, h: 30, label: evtType };
        w = cfg.w || 100;
        h = cfg.h || (cfg.r ? cfg.r * 2 : 30);
      }

      if (x + w + NODE_GAP_X > startX + MAX_ROW_WIDTH && rowNodes.length > 0) {
        x = startX;
        y += maxRowHeight + INTRA_ROW_GAP;
        maxRowHeight = 0;
      }

      const nodeObj = {
        x: x, y: y, w: w, h: h,
        cx: x + w / 2, cy: y + h / 2,
        event: evt, session_id: sid, type: evtType, config: cfg
      };

      if (evtType === 'round') {
        nodeObj.roundTools = gEvt.tools || [];
        nodeObj.hasTools = gEvt.hasTools || false;
        nodeObj.llmData = gEvt.llmData || {};
      }

      rowNodes.push(nodeObj);
      x += w + NODE_GAP_X;
      maxRowHeight = Math.max(maxRowHeight, h);
    }

    const endY = y + maxRowHeight;
    sessionRows[sid] = { y: startY, nodes: rowNodes, session: sessionNode };
    allNodes.push(...rowNodes);
    return { endX: x, endY };
  }

  function layoutRecursive(sessionNode, startX, startY) {
    const { endX, endY } = layoutSession(sessionNode, startX, startY);

    if (sessionNode.children && sessionNode.children.length > 0) {
      const spawnNode = sessionRows[sessionNode.session_id].nodes.find(
        n => n.type === 'spawn_agents_started'
      );
      const branchX = spawnNode ? spawnNode.cx : startX;

      const nextRowY = endY + ROW_GAP_Y;
      const childWidth = Math.max(200, (endX - startX) / sessionNode.children.length);

      for (let i = 0; i < sessionNode.children.length; i++) {
        const child = sessionNode.children[i];
        const childStartX = branchX + (i - (sessionNode.children.length - 1) / 2) * childWidth;
        const childRowY = nextRowY;

        if (spawnNode) {
          spawnNode.branchTargets = spawnNode.branchTargets || [];
          spawnNode.branchTargets.push({ childSid: child.session_id, childRowY });
        }

        layoutRecursive(child, Math.max(MARGIN_X, childStartX), childRowY);

        const childRow = sessionRows[child.session_id];
        if (childRow) {
          const completeNode = childRow.nodes.find(n =>
            n.type === 'subagent_completed' || n.type === 'subagent_failed'
          );
          if (completeNode) {
            completeNode.returnToParent = true;
            completeNode.parentSid = sessionNode.session_id;
          }
        }
      }
    }

    return endX;
  }

  if (timeline && timeline.root) {
    layoutRecursive(timeline.root, MARGIN_X, MARGIN_Y);
  }

  return { allNodes, sessionRows };
}

/** 根据布局结果计算所需的总画布高度 */
function computeTotalHeight(layout) {
  let maxY = 0;
  for (const node of layout.allNodes) {
    maxY = Math.max(maxY, node.y + node.h + 20);
  }
  return maxY;
}

// ============================================================
// 连线绘制
// ============================================================

/**
 * 绘制三类连线：
 * 1. 同 session 内相邻节点的连线（支持换行：水平+垂直折线）
 * 2. spawn_agents_started → 各子代理首节点的贝塞尔分叉曲线
 * 3. 子代理完成/失败 → 父代理行的贝塞尔收束曲线
 */
/** 绘制箭头辅助函数 */
function drawArrow(x1, y1, x2, y2, color, lineWidth = 1.8) {
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();

  // 绘制箭头
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const arrowLen = 8;
  const arrowAngle = Math.PI / 6;

  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(
    x2 - arrowLen * Math.cos(angle - arrowAngle),
    y2 - arrowLen * Math.sin(angle - arrowAngle)
  );
  ctx.moveTo(x2, y2);
  ctx.lineTo(
    x2 - arrowLen * Math.cos(angle + arrowAngle),
    y2 - arrowLen * Math.sin(angle + arrowAngle)
  );
  ctx.stroke();
}

function drawConnections(layout) {
  // 1. 同一 session 内节点间直线箭头连线
  for (const sid of Object.keys(layout.sessionRows)) {
    const row = layout.sessionRows[sid];
    if (row.nodes.length < 2) continue;
    for (let i = 0; i < row.nodes.length - 1; i++) {
      const a = row.nodes[i];
      const b = row.nodes[i + 1];

      // 判断是否换行
      const isWrapped = b.y > a.y && b.x <= a.x;

      if (isWrapped) {
        // 换行：两段直线箭头（右→下→左）
        const midY = a.y + a.h + Math.round((b.y - (a.y + a.h)) / 2);
        // 第一段：从 a 右侧到中点
        drawArrow(a.x + a.w, a.cy, a.x + a.w + 10, a.cy, '#d0d0d0', 1.8);
        // 第二段：垂直向下
        drawArrow(a.x + a.w + 10, a.cy, a.x + a.w + 10, midY, '#d0d0d0', 1.8);
        // 第三段：到中点向右
        drawArrow(a.x + a.w + 10, midY, b.x - 10, midY, '#d0d0d0', 1.8);
        // 第四段：到 b 左侧
        drawArrow(b.x - 10, midY, b.x, b.cy, '#d0d0d0', 1.8);
      } else {
        // 同行：直接水平箭头
        drawArrow(a.x + a.w, a.cy, b.x, b.cy, '#d0d0d0', 1.8);
      }
    }
  }

  // 2. 父→子 分叉直线箭头
  for (const node of layout.allNodes) {
    if (node.branchTargets) {
      for (const target of node.branchTargets) {
        const childRow = layout.sessionRows[target.childSid];
        if (!childRow || childRow.nodes.length === 0) continue;
        const childFirst = childRow.nodes[0];
        drawArrow(node.cx, node.y + node.h, childFirst.cx, childFirst.y, '#3498db', 1.8);
      }
    }

    // 3. 子代理完成/失败 → 父代理行 收束直线箭头
    if (node.returnToParent && node.parentSid) {
      const parentRow = layout.sessionRows[node.parentSid];
      if (parentRow) {
        const targetX = node.cx;
        drawArrow(node.cx, node.y + node.h, targetX, parentRow.y, '#27ae60', 1.5);
      }
    }
  }
}

// ============================================================
// 节点形状绘制函数
// ============================================================

function drawRectNode(node, phaseColor, isError, isHighlighted) {
  const { x, y, w, h, type } = node;
  const evt = node.event;

  // 顶部色条：错误/失败节点红色，tool_result成功绿色
  const isFailedType = type === 'subagent_failed' || type === 'error' || type === 'llm_error';
  const showRedBar = isError || isFailedType;
  const showGreenBar = type === 'tool_result' && evt.data?.success === true;
  const barHeight = 3;

  // 统一深色背景
  ctx.fillStyle = isError ? '#3a2020' : '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = isError ? '#4a3030' : '#3a3a3a';

  roundedRect(x, y, w, h, 6);
  ctx.fill();

  ctx.strokeStyle = isError ? '#E74C3C' : phaseColor;
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
  ctx.stroke();

  // 绘制顶部色条
  if (showRedBar) {
    ctx.fillStyle = '#E74C3C';
    ctx.fillRect(x, y, w, barHeight);
  } else if (showGreenBar) {
    ctx.fillStyle = '#27ae60';
    ctx.fillRect(x, y, w, barHeight);
  }

  ctx.fillStyle = '#fff';
  ctx.font = isHighlighted ? `bold 13px ${FONT_STACK}` : `12px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const label = node.summary || getEventSummary(node);
  const truncatedLabel = truncateTextToFit(ctx, label, w - 10);
  ctx.fillText(truncatedLabel, x + w / 2, y + h / 2 + (showRedBar || showGreenBar ? 1 : 0));
}

function drawCardNode(node, phaseColor, isError, isHighlighted) {
  const { x, y, w, h, type = 'unknown' } = node;
  const evt = node.event;

  // 统一深色背景
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';
  roundedRect(x, y, w, h, 4);
  ctx.fill();
  ctx.strokeStyle = isError ? '#E74C3C' : phaseColor;
  ctx.lineWidth = isHighlighted ? 3 : 1.8;
  ctx.stroke();

  // 顶部色条高度改为 18px
  ctx.fillStyle = phaseColor;
  ctx.fillRect(x, y, w, 18);

  ctx.fillStyle = '#fff';
  ctx.font = `bold 12px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const title = type === 'tool_call' && evt.data ? evt.data.tool_name || type : type;
  const truncatedTitle = truncateTextToFit(ctx, title, w - 10);
  ctx.fillText(truncatedTitle, x + w / 2, y + 8);

  ctx.fillStyle = '#bbb';
  ctx.font = `10px ${FONT_STACK}`;
  if (evt.data && evt.data.arguments) {
    const argsStr = typeof evt.data.arguments === 'string' ? evt.data.arguments : JSON.stringify(evt.data.arguments);
    const truncatedArgs = truncateTextToFit(ctx, argsStr, w - 10);
    ctx.fillText(truncatedArgs, x + w / 2, y + 28);
  }
}

function drawRoundNode(node, phaseColor, isError, isHighlighted) {
  const { x, y, w, h } = node;
  const tools = node.roundTools || [];
  const llmData = node.llmData || {};
  const hasTools = node.hasTools;

  // 使用深色背景确保文字对比度
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';
  roundedRect(x, y, w, h, 8);
  ctx.fill();

  ctx.strokeStyle = isError ? '#E74C3C' : phaseColor;
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
  ctx.stroke();

  const barH = 22;
  // 顶部彩色 bar 使用阶段色
  ctx.fillStyle = phaseColor;
  roundedRect(x, y, w, barH, { tl: 8, tr: 8, br: 0, bl: 0 });
  ctx.fill();

  const timing = llmData.timing_ms ? `${(llmData.timing_ms / 1000).toFixed(1)}s` : '';
  const iterLabel = hasTools ? `R${node.event.iteration || '?'}` : '';
  const phaseLabel = node.event.phase || '';

  ctx.fillStyle = '#fff';
  ctx.font = `bold 11px ${FONT_STACK}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  if (timing) ctx.fillText(`⏱ ${timing}`, x + 10, y + barH / 2);

  ctx.textAlign = 'right';
  if (iterLabel || phaseLabel) {
    ctx.font = `bold 10px ${FONT_STACK}`;
    ctx.fillText(`${iterLabel} ${phaseLabel}`.trim(), x + w - 10, y + barH / 2);
  }

  const reasoningRowH = llmData.reasoning_content ? 16 : 0;
  if (llmData.reasoning_content) {
    ctx.fillStyle = '#fff';
    ctx.font = `bold 10px ${FONT_STACK}`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const maxWidth = w - 16;
    const displayText = truncateTextToFit(ctx, llmData.reasoning_content, maxWidth);
    ctx.fillText(displayText, x + 8, y + barH + 4 + 6);
  }

  const innerY = y + barH + 6 + reasoningRowH;

  if (hasTools && tools.length > 0) {
    const chipW = 78;
    const chipH = 30;
    const chipGap = 4;
    const totalChipW = tools.length * chipW + (tools.length - 1) * chipGap;
    let chipX = x + Math.max(8, (w - totalChipW) / 2);

    for (let ti = 0; ti < tools.length; ti++) {
      const t = tools[ti];
      const tc = t.call?.data || {};
      const tr = t.result?.data || {};

      const toolName = (tc.tool_name || '').split('/').pop().split(':').shift() || '工具';
      const shortName = truncateTextToFit(ctx, toolName, chipW - 8);

      const success = tr.success === true ? true : (tr.success === false ? false : null);
      const hasError = tr.error && tr.error.length > 0;
      const isErrResultType = (tr.result_type || '').indexOf('error') >= 0;
      const isSuccess = success === true;
      const isFail = success === false || hasError || isErrResultType;

      // 深色背景，高对比度文字
      const chipBg = isFail ? '#4a2020' : (isSuccess ? '#1a3a20' : '#333');
      ctx.fillStyle = chipBg;
      roundedRect(chipX, innerY, chipW, chipH, 3);
      ctx.fill();

      ctx.fillStyle = isFail ? '#E74C3C' : (isSuccess ? '#27ae60' : phaseColor);
      ctx.fillRect(chipX, innerY, 3, chipH);

      ctx.strokeStyle = isFail ? '#E74C3C' : (isSuccess ? '#27ae60' : phaseColor);
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = '#fff';
      ctx.font = `bold 9px ${FONT_STACK}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(shortName, chipX + chipW / 2 + 1.5, innerY + 12);

      ctx.fillStyle = '#bbb';
      ctx.font = `7px ${FONT_STACK}`;
      const rt = (tr.result_type || '').replace(/_/g, '');
      const truncatedRt = truncateTextToFit(ctx, rt, chipW - 8);
      ctx.fillText(truncatedRt, chipX + chipW / 2 + 1.5, innerY + 23);

      chipX += chipW + chipGap;
    }
  } else {
    ctx.fillStyle = '#fff';
    ctx.font = `bold 12px ${FONT_STACK}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const content = llmData.content || '回复';
    const truncatedContent = truncateTextToFit(ctx, content, w - 16);
    ctx.fillText(truncatedContent, x + w / 2, innerY + 18);
  }
}

function drawBubbleNode(node, phaseColor, isError, isHighlighted) {
  const { x, y, w, h } = node;

  // 统一深色背景
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';

  const r = 10;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r + 10, y + h);
  ctx.lineTo(x + 5, y + h + 8);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = isError ? '#E74C3C' : phaseColor;
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
  ctx.stroke();

  ctx.fillStyle = '#fff';
  ctx.font = `italic 11px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const content = node.summary || getEventSummary(node);
  const truncatedContent = truncateTextToFit(ctx, content, w - 16);
  ctx.fillText(truncatedContent, x + w / 2, y + h / 2 - 2);
}

function drawTagNode(node, phaseColor, isError, isHighlighted) {
  const { x, y, w, h } = node;
  const evt = node.event;

  const data = evt.data || {};
  const success = data.success === true ? true : (data.success === false ? false : null);
  // 左侧 3px 色条：绿色成功、红色失败/错误、灰色其他
  const barColor = success === true ? '#27ae60' : (success === false || isError ? '#E74C3C' : phaseColor);

  // 统一深色背景
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';
  roundedRect(x, y, w, h, 4);
  ctx.fill();
  ctx.strokeStyle = barColor;
  ctx.lineWidth = isHighlighted ? 2 : 1;
  ctx.stroke();

  // 左侧色条
  ctx.fillStyle = barColor;
  ctx.fillRect(x, y, 3, h);

  ctx.fillStyle = '#fff';
  ctx.font = `12px ${FONT_STACK}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const label = node.summary || getEventSummary(node);
  const truncatedLabel = truncateTextToFit(ctx, label, w - 10);
  ctx.fillText(truncatedLabel, x + w / 2 + 1.5, y + h / 2);
}

function drawCircleNode(node, phaseColor, isHighlighted) {
  const { cx, cy } = node;
  const r = node.config.r || 6;

  // 统一使用深色填充，阶段色描边
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = phaseColor;
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
  ctx.stroke();
}

function drawDiamondNode(node, phaseColor, isHighlighted) {
  const { cx, cy } = node;
  const s = 14;

  // 统一使用深色填充，阶段色描边
  ctx.fillStyle = '#2a2a2a';
  if (isHighlighted) ctx.fillStyle = '#3a3a3a';
  ctx.beginPath();
  ctx.moveTo(cx, cy - s);
  ctx.lineTo(cx + s, cy);
  ctx.lineTo(cx, cy + s);
  ctx.lineTo(cx - s, cy);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = phaseColor;
  ctx.lineWidth = isHighlighted ? 2.5 : 1.5;
  ctx.stroke();
}

/**
 * 批量绘制所有节点
 * @param {Array} nodes - computeLayout 产出的 allNodes
 * @param {number} highlightIndex - state.events 中高亮的事件索引
 */
function drawNodes(nodes, highlightIndex) {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    node.summary = getEventSummary(node);
    const evt = node.event;
    const phase = evt.phase || '';
    const phaseColor = getPhaseColor(phase);
    const isError = node.type === 'error' || node.type === 'llm_error';
    const isHighlighted = (state.events[highlightIndex] === evt);

    ctx.save();

    // 为所有节点添加阴影效果增强立体感
    ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
    ctx.shadowBlur = 8;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 3;

    if (isHighlighted) {
      ctx.shadowColor = phaseColor;
      ctx.shadowBlur = 20;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 4;
    }

    const cfg = node.config;

    switch (cfg.shape) {
      case 'rect':
        drawRectNode(node, phaseColor, isError, isHighlighted);
        break;
      case 'card':
        drawCardNode(node, phaseColor, isError, isHighlighted);
        break;
      case 'round':
        drawRoundNode(node, phaseColor, isError, isHighlighted);
        break;
      case 'bubble':
        drawBubbleNode(node, phaseColor, isError, isHighlighted);
        break;
      case 'tag':
        drawTagNode(node, phaseColor, isError, isHighlighted);
        break;
      case 'circle':
        drawCircleNode(node, phaseColor, isHighlighted);
        break;
      case 'diamond':
        drawDiamondNode(node, phaseColor, isHighlighted);
        break;
      default:
        drawRectNode(node, phaseColor, isError, isHighlighted);
    }

    ctx.restore();
  }
}

// ============================================================
// 主渲染入口
// ============================================================

/** 绘制 Canvas 时间线（全局 / 子代理两种视图） */
function renderTimeline() {
  if (!ctx || !dom.canvas) return;

  const dpr = window.devicePixelRatio || 1;
  let w = dom.canvas.width / dpr;
  let h = dom.canvas.height / dpr;
  ctx.clearRect(0, 0, dom.canvas.width, dom.canvas.height);

  if (!state.timeline || state.events.length === 0) {
    drawSolidBackground(w, h);
    ctx.fillStyle = '#fff';
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('请加载 JSONL 文件以查看时间线', w / 2, h / 2);
    return;
  }

  // 子代理展开视图
  if (state.viewMode === 'subagent' && state.expandedAgentId) {
    drawSolidBackground(w, h);
    renderSubagentTimeline(w, h);
    return;
  }

  // 全局 DAG 视图
  const layout = computeLayout(state.timeline, w);
  const totalH = computeTotalHeight(layout) + 60;
  if (totalH > h) {
    dom.canvas.height = Math.round(totalH * dpr);
    dom.canvas.style.height = totalH + 'px';
    w = dom.canvas.width / dpr;
    h = dom.canvas.height / dpr;
    ctx.scale(dpr, dpr);
    ctx.textRendering = 'geometricPrecision';
    ctx.imageSmoothingEnabled = false;
  }

  // 在尺寸调整之后重新绘制网格背景（关键修复！）
  drawSolidBackground(w, h);
  drawConnections(layout);
  drawNodes(layout.allNodes, state.currentIndex);
}

function initTooltip() {
  tooltipEl = document.getElementById('nodeTooltip');
}

function showTooltip(node, clientX, clientY) {
  if (!tooltipEl) return;
  const evt = node.event;
  const phase = evt.phase || '';
  const phaseColor = getPhaseColor(phase);
  const data = evt.data || {};

  if (node.type === 'round' && node.roundTools && node.roundTools.length > 0) {
    let html = `<div class="tt-title">🔄 Round ${evt.iteration || '?'} · ${(node.llmData?.timing_ms || 0 / 1000).toFixed(1)}s · ${phase}</div>`;
    if (node.llmData?.reasoning_content) {
      html += `<div style="margin-top:6px;background:#1a1a1a;border-radius:6px;padding:8px 10px;font-size:11px;color:#fff;line-height:1.5;max-width:360px;word-break:break-word;"><span style="font-weight:600;color:#aaa;">Reasoning:</span><br>${escapeHtml(node.llmData.reasoning_content)}</div>`;
    }
    html += `<div style="margin-top:6px;font-weight:600;font-size:11px;color:#ccc;">Tools (${node.roundTools.length}):</div>`;

    for (let ti = 0; ti < node.roundTools.length; ti++) {
      const t = node.roundTools[ti];
      const tc = t.call?.data || {};
      const tr = t.result?.data || {};
      const name = tc.tool_name || '?';
      const rt = tr.result_type || '';
      const ok = tr.success === true;
      const fail = tr.success === false || (tr.error && tr.error.length > 0);
      const icon = ok ? '✓' : (fail ? '✗' : '▸');
      const color = ok ? '#27ae60' : (fail ? '#E74C3C' : '#888');

      html += `<div class="tt-row" style="margin-top:2px;">
        <span style="color:${color};font-weight:bold;margin-right:4px;">${icon}</span>
        <span class="tt-val">${escapeHtml(name)}</span>
        <span style="color:#aaa;margin-left:4px;">→ ${escapeHtml(rt.replace(/_/g,' '))}</span>
      </div>`;
    }

    tooltipEl.innerHTML = html;
    tooltipEl.style.display = 'block';

    const rect = tooltipEl.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = clientX + 16;
    let top = clientY + 16;
    if (left + rect.width > vw) left = clientX - rect.width - 8;
    if (top + rect.height > vh) top = clientY - rect.height - 8;
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = top + 'px';
    tooltipEl.classList.add('visible');
    return;
  }

  let html = `<div class="tt-title">${escapeHtml((evt.event_type || '').replace(/_/g, ' '))}</div>`;
  html += `<div class="tt-row"><span class="tt-dot" style="background:${phaseColor}"></span><span class="tt-val">${escapeHtml(phase || 'DEFAULT')}</span></div>`;
  html += `<div class="tt-row"><span class="tt-key">Agent:</span><span class="tt-val">${escapeHtml(evt.agent_id || '-')}</span></div>`;
  html += `<div class="tt-row"><span class="tt-key">Time:</span><span class="tt-val">${escapeHtml(evt.timestamp || '-')}</span></div>`;

  if (data.tool_name) {
    html += `<div class="tt-row"><span class="tt-key">Tool:</span><span class="tt-val">${escapeHtml(data.tool_name)}</span></div>`;
  }
  if (data.success !== undefined) {
    html += `<div class="tt-row"><span class="tt-key">Status:</span><span class="tt-val" style="color:${data.success ? '#27ae60' : '#E74C3C'}">${data.success ? '成功' : '失败'}</span></div>`;
  }
  if (data.content) {
    html += `<div class="tt-data">${escapeHtml(String(data.content).substring(0, 200))}</div>`;
  } else if (Object.keys(data).length > 0) {
    html += `<div class="tt-data">${escapeHtml(JSON.stringify(data, null, 2).substring(0, 300))}</div>`;
  }

  tooltipEl.innerHTML = html;
  tooltipEl.style.display = 'block';

  // 位置计算：鼠标右下方，超出视口时调整
  const rect = tooltipEl.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = clientX + 16;
  let top = clientY + 16;
  if (left + rect.width > vw) left = clientX - rect.width - 8;
  if (top + rect.height > vh) top = clientY - rect.height - 8;
  tooltipEl.style.left = left + 'px';
  tooltipEl.style.top = top + 'px';
  tooltipEl.classList.add('visible');
}

function hideTooltip() {
  if (!tooltipEl) return;
  tooltipEl.classList.remove('visible');
  setTimeout(() => {
    if (!tooltipEl.classList.contains('visible')) {
      tooltipEl.style.display = 'none';
    }
  }, 150);
}

/**
 * 子代理展开视图：横向排列该子代理的所有事件
 */
function renderSubagentTimeline(w, h) {
  const agentSid = Object.keys(state.timeline.sessions).find(
    sid => state.timeline.sessions[sid].agent_id === state.expandedAgentId
  );
  if (!agentSid) {
    ctx.fillStyle = '#fff';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('未找到子代理数据', w / 2, h / 2);
    return;
  }

  const sessionNode = state.timeline.sessions[agentSid];
  const events = sessionNode.events;

  const MARGIN = 30;
  const NODE_W = 140;
  const NODE_H = 40;
  const GAP = 15;
  let x = MARGIN;
  const y = 60;

  ctx.fillStyle = '#fff';
  ctx.font = 'bold 16px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('子代理: ' + state.expandedAgentId, MARGIN, 30);

  ctx.fillStyle = '#bbb';
  ctx.font = '12px sans-serif';
  ctx.fillText('← 点击画布返回全局', MARGIN + 200, 30);

  for (let i = 0; i < events.length; i++) {
    const evt = events[i];
    // 跳过 iteration_start / iteration_end
    if (evt.event_type === 'iteration_start' || evt.event_type === 'iteration_end') {
      continue;
    }
    const phase = evt.phase || '';
    const color = getPhaseColor(phase);
    const isHighlighted = (state.currentIndex < state.events.length) && (state.events[state.currentIndex] === evt);

    drawRectNode(
      { x, y, w: NODE_W, h: NODE_H, event: evt, type: evt.event_type, config: NODE_CONFIG[evt.event_type] || {} },
      color, evt.event_type === 'error', isHighlighted
    );

    ctx.fillStyle = '#999';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('evt_' + (i + 1), x + NODE_W / 2, y + NODE_H + 12);

    x += NODE_W + GAP;
  }
}

// ============================================================
// 播放控制
// ============================================================

/** 开始播放 */
function play() {
  if (state.events.length === 0) return;
  pause(); // 清除已有定时器

  const interval = Math.max(100, 1000 / state.speed);
  state.playTimer = setInterval(() => {
    if (state.currentIndex >= state.events.length - 1) {
      pause();
      state.isPlaying = false;
      dom.btnPlay.classList.remove('playing');
      dom.btnPlay.innerHTML = '&#9654;';
      return;
    }
    state.currentIndex++;
    dom.progressBar.value = state.currentIndex;
    dom.positionLabel.textContent = `事件 ${state.currentIndex + 1} / ${state.events.length}`;
    renderTimeline();
    updateDetailPanel(state.events[state.currentIndex]);
  }, interval);
}

/** 暂停播放 */
function pause() {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
}

/** 前进一步 */
function stepForward() {
  if (state.currentIndex < state.events.length - 1) {
    state.currentIndex++;
  }
  updateDetailPanel(state.events[state.currentIndex] || null);
}

/** 后退一步 */
function stepBack() {
  if (state.currentIndex > 0) {
    state.currentIndex--;
  }
  updateDetailPanel(state.events[state.currentIndex] || null);
}

/** 设置播放速度 */
function setSpeed(speed) {
  state.speed = speed;
  if (state.isPlaying) {
    // 重置定时器以应用新速度
    play();
  }
}

/** 跳转到指定位置 */
function jumpTo(index) {
  if (index >= 0 && index < state.events.length) {
    state.currentIndex = index;
  }
  renderTimeline();
  updateDetailPanel(state.events[state.currentIndex] || null);
}

// ============================================================
// 详情面板
// ============================================================

/**
 * 更新右侧详情面板，渲染事件详情
 * @param {Object|null} event - 事件对象
 */
function updateDetailPanel(event, roundNode = null) {
  const panel = dom.detailPanel;
  if (!panel) return;

  if (!event) {
    panel.innerHTML = '<p class="detail-placeholder">无事件数据</p>';
    return;
  }

  if (!event.event_type) {
    panel.innerHTML = '<p style="color:#aaa">此记录无事件类型（可能是旧版交互日志）</p>';
    return;
  }

  const data = event.data || {};
  const phaseColors = {
    COLLECT: '#4A90D9',
    PLAN: '#F5A623',
    EXECUTE: '#7ED321',
    REPORT: '#9B59B6',
    DEFAULT: '#95A5A6'
  };
  const phase = event.phase || '';
  const phaseColor = phaseColors[phase] || phaseColors.DEFAULT;

  let html = '';

  // 阶段标签
  html += '<div style="margin-bottom: 12px;">';
  html += `<span style="display:inline-block;padding:2px 10px;border-radius:3px;background:${phaseColor};color:#fff;font-size:12px;font-weight:600;">${phase || 'UNKNOWN'}</span>`;
  html += ` <strong style="font-size:15px;">${escapeHtml(event.event_type || event.type || '-')}</strong>`;
  html += '</div>';

  // 元数据
  html += '<div class="detail-meta">';
  html += `<p><strong>Event ID:</strong> ${escapeHtml(event.event_id || '-')}</p>`;
  html += `<p><strong>Agent:</strong> ${escapeHtml(event.agent_id || '-')}</p>`;
  html += `<p><strong>Session:</strong> ${escapeHtml(event.session_id || '-')}</p>`;
  html += `<p><strong>Iteration:</strong> ${event.iteration != null ? event.iteration : '-'}</p>`;
  html += `<p><strong>Phase:</strong> <span style="color:${phaseColor}">${phase || '-'}</span></p>`;
  html += `<p><strong>Time:</strong> ${escapeHtml(event.timestamp || '-')}</p>`;
  if (event.parent_agent_id) {
    html += `<p><strong>Parent Agent:</strong> ${escapeHtml(event.parent_agent_id)}</p>`;
  }
  if (event.parent_session_id) {
    html += `<p><strong>Parent Session:</strong> ${escapeHtml(event.parent_session_id)}</p>`;
  }
  html += '</div>';

  html += '<hr style="margin:12px 0;border:none;border-top:1px solid #555;">';

  // 如果是 Round 节点且有工具调用，显示工具调用详情
  if (roundNode && roundNode.roundTools && roundNode.roundTools.length > 0) {
    html += `<h4 style="margin-bottom:8px;color:#fff;">工具调用 (${roundNode.roundTools.length})</h4>`;

    for (let ti = 0; ti < roundNode.roundTools.length; ti++) {
      const t = roundNode.roundTools[ti];
      const tc = t.call?.data || {};
      const tr = t.result?.data || {};
      const toolName = tc.tool_name || '未知工具';
      const success = tr.success;
      const hasError = tr.error && tr.error.length > 0;
      const isErrResultType = (tr.result_type || '').indexOf('error') >= 0;
      const isSuccess = success === true;
      const isFail = success === false || hasError || isErrResultType;

      const statusColor = isFail ? '#E74C3C' : (isSuccess ? '#27ae60' : '#aaa');
      const statusText = isFail ? '失败' : (isSuccess ? '成功' : '执行中');
      const statusIcon = isFail ? '✗' : (isSuccess ? '✓' : '▸');

      html += `<div style="margin-bottom:12px;padding:10px;background:#1a1a1a;border-radius:6px;border-left:3px solid ${statusColor};">`;
      html += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">`;
      html += `<strong style="color:#fff;font-size:13px;">${escapeHtml(toolName)}</strong>`;
      html += `<span style="color:${statusColor};font-weight:600;font-size:12px;">${statusIcon} ${statusText}</span>`;
      html += `</div>`;

      // 工具参数
      if (tc.arguments) {
        html += `<div style="margin-bottom:6px;">`;
        html += `<span style="color:#aaa;font-size:11px;">参数:</span>`;
        html += `<pre style="margin:4px 0 0 0;padding:6px;background:#0f0f0f;border-radius:4px;font-size:11px;color:#ddd;white-space:pre-wrap;word-break:break-all;">${escapeHtml(JSON.stringify(tc.arguments, null, 2))}</pre>`;
        html += `</div>`;
      }

      // 工具结果
      if (tr.result_type) {
        html += `<div style="margin-bottom:4px;">`;
        html += `<span style="color:#aaa;font-size:11px;">结果类型:</span> <span style="color:#ddd;font-size:12px;">${escapeHtml(tr.result_type)}</span>`;
        html += `</div>`;
      }

      if (tr.error) {
        html += `<div style="margin-bottom:4px;">`;
        html += `<span style="color:#aaa;font-size:11px;">错误:</span> <span style="color:#E74C3C;font-size:12px;">${escapeHtml(String(tr.error))}</span>`;
        html += `</div>`;
      }

      if (tr.output_length !== undefined) {
        html += `<div style="margin-bottom:4px;">`;
        html += `<span style="color:#aaa;font-size:11px;">输出长度:</span> <span style="color:#ddd;font-size:12px;">${tr.output_length}</span>`;
        html += `</div>`;
      }

      html += `</div>`;
    }

    html += '<hr style="margin:12px 0;border:none;border-top:1px solid #555;">';
  }

  // 数据正文
  html += '<h4 style="margin-bottom:6px;">Data</h4>';
  html += `<pre class="detail-data">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;

  panel.innerHTML = html;
}

/**
 * HTML 转义，防止 XSS
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ============================================================
// Subagent 视图切换 (占位)
// ============================================================

/** 展开某个 subagent 的时间线细节 */
function expandSubagent(agentId) {
  state.viewMode = 'subagent';
  state.expandedAgentId = agentId;
  renderTimeline();
}

/** 收拢回全局视图 */
function collapseToGlobal() {
  state.viewMode = 'global';
  state.expandedAgentId = null;
  renderTimeline();
}

// ============================================================
// 辅助：统一的文件加载处理
// ============================================================

/**
 * 处理多个文件的并发读取与合并
 * @param {File[]} files - 文件对象数组
 */
function handleMultipleFiles(files) {
  const readers = files.map(file => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsText(file);
    });
  });

  Promise.all(readers).then(contents => {
    const allText = contents.join('\n');
    handleFileContent(allText);
  }).catch(err => {
    alert('文件读取失败: ' + err.message);
  });
}

/**
 * 处理文件内容加载后的完整流程
 * @param {string} text - 文件原始文本
 */
function handleFileContent(text) {
  // 空文本检查
  if (!text || text.trim() === '') {
    dom.eventCount.textContent = '已加载 0 个事件';
    dom.eventCount.style.color = '';
    alert('文件内容为空');
    return;
  }

  const { events, errors } = parseJSONL(text);

  // 构建时间线（内部会统计跳过的旧格式记录数）
  state.timeline = buildTimeline(events);
  const skipped = state.timeline.skippedCount || 0;
  const validEvents = events.length - skipped;

  // 显示解析错误和跳过统计
  if (errors.length > 0) {
    const errorMsg = `警告: ${errors.length} 行解析失败`;
    dom.eventCount.textContent = skipped > 0
      ? `已加载 ${events.length} 条记录（含 ${validEvents} 个事件，跳过 ${skipped} 条旧格式交互记录）(${errorMsg})`
      : `已加载 ${events.length} 个事件 (${errorMsg})`;
    dom.eventCount.style.color = '#E74C3C';
    console.warn('JSONL 解析错误:', errors);
  } else {
    dom.eventCount.textContent = skipped > 0
      ? `已加载 ${events.length} 条记录（含 ${validEvents} 个事件，跳过 ${skipped} 条旧格式交互记录）`
      : `已加载 ${events.length} 个事件`;
    dom.eventCount.style.color = '';
  }

  // 更新全局状态
  state.events = events;
  state.currentIndex = 0;

  // 更新进度条与位置标签
  dom.progressBar.max = Math.max(0, validEvents - 1);
  dom.progressBar.value = 0;
  dom.positionLabel.textContent = validEvents > 0
    ? `事件 1 / ${validEvents}`
    : '- / -';

  // 更新详情面板
  updateDetailPanel(events.length > 0 ? events[0] : null);

  // 渲染画布
  renderTimeline();
}

/**
 * 重置所有状态并清空画布
 */
function resetAll() {
  pause();
  state.events = [];
  state.timeline = null;
  state.currentIndex = 0;
  state.isPlaying = false;
  state.viewMode = 'global';
  state.expandedAgentId = null;

  if (ctx && dom.canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = dom.canvas.width / dpr;
    const h = dom.canvas.height / dpr;
    ctx.clearRect(0, 0, dom.canvas.width, dom.canvas.height);
    drawSolidBackground(w, h);
    ctx.fillStyle = '#fff';
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('请加载 JSONL 文件以查看时间线', w / 2, h / 2);
  }

  dom.eventCount.textContent = '已加载 0 个事件';
  dom.eventCount.style.color = '';
  dom.progressBar.max = 0;
  dom.progressBar.value = 0;
  dom.positionLabel.textContent = '事件 0 / 0';
  dom.detailPanel.innerHTML = '<p class="detail-placeholder">点击时间线中的事件查看详情</p>';
  dom.btnPlay.textContent = '\u25B6';
  dom.btnPlay.classList.remove('playing');
}

// ============================================================
// 事件绑定
// ============================================================

// --- 文件选择 ---
dom.fileInput.addEventListener('change', (e) => {
  const files = [...e.target.files];
  if (files.length > 0) handleMultipleFiles(files);
});

// --- 拖拽支持 ---
const dragTargets = [dom.dropHint, document.body];

dragTargets.forEach((el) => {
  el.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dom.dropHint.classList.add('drag-over');
  });

  el.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dom.dropHint.classList.remove('drag-over');
  });

  el.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dom.dropHint.classList.remove('drag-over');
    const files = [...e.dataTransfer.files].filter(f => f.name.endsWith('.jsonl'));
    if (files.length > 0) handleMultipleFiles(files);
  });
});

// --- Canvas resize 监听 ---
function resizeCanvas() {
  const wrapper = document.getElementById('canvasWrapper');
  const wrapperWidth = wrapper ? wrapper.clientWidth : dom.canvas.parentElement.getBoundingClientRect().width - 320;
  const width = wrapperWidth;
  const height = wrapper ? wrapper.clientHeight : dom.canvas.parentElement.getBoundingClientRect().height;

  const dpr = window.devicePixelRatio || 1;

  if (dom.canvas.width !== Math.round(width * dpr) || dom.canvas.height !== Math.round(height * dpr)) {
    dom.canvas.width = Math.round(width * dpr);
    dom.canvas.height = Math.round(height * dpr);
    dom.canvas.style.width = width + 'px';
    dom.canvas.style.height = height + 'px';
    ctx.scale(dpr, dpr);
    ctx.textRendering = 'geometricPrecision';
    ctx.imageSmoothingEnabled = false;
  }
  // 始终渲染，确保网格背景显示
  renderTimeline();
}

window.addEventListener('resize', resizeCanvas);
// 初始调用
resizeCanvas();

// --- 播放控制按钮 ---
dom.btnPlay.addEventListener('click', () => {
  if (state.isPlaying) {
    pause();
  } else {
    play();
  }
  state.isPlaying = !state.isPlaying;
  dom.btnPlay.classList.toggle('playing', state.isPlaying);
  dom.btnPlay.innerHTML = state.isPlaying ? '&#9646;&#9646;' : '&#9654;';
});

dom.btnPrev.addEventListener('click', () => {
  stepBack();
  dom.progressBar.value = state.currentIndex;
  dom.positionLabel.textContent = `事件 ${state.currentIndex + 1} / ${state.events.length}`;
  renderTimeline();
});

dom.btnNext.addEventListener('click', () => {
  stepForward();
  dom.progressBar.value = state.currentIndex;
  dom.positionLabel.textContent = `事件 ${state.currentIndex + 1} / ${state.events.length}`;
  renderTimeline();
});

// --- 速度选择 ---
dom.speedSelect.addEventListener('change', (e) => {
  const newSpeed = parseInt(e.target.value, 10);
  setSpeed(newSpeed);
  state.speed = newSpeed;
});

// --- 进度条 ---
dom.progressBar.addEventListener('input', (e) => {
  const index = parseInt(e.target.value, 10);
  jumpTo(index);
  state.currentIndex = index;
  dom.positionLabel.textContent = `事件 ${state.currentIndex + 1} / ${state.events.length}`;
  renderTimeline();
});

// --- 清空按钮 ---
dom.btnClear.addEventListener('click', resetAll);

// --- Canvas 鼠标移动 (tooltip) ---
dom.canvas.addEventListener('mousemove', (e) => {
  if (state.viewMode === 'subagent') return;
  if (!state.timeline) return;

  const rect = dom.canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const dpr = window.devicePixelRatio || 1;
  const scaleX = (dom.canvas.width / dpr) / rect.width;
  const scaleY = (dom.canvas.height / dpr) / rect.height;
  const cx = mx * scaleX;
  const cy = my * scaleY;

  const layout = computeLayout(state.timeline, dom.canvas.width / dpr);
  let found = null;
  for (const node of layout.allNodes) {
    if (cx >= node.x && cx <= node.x + node.w && cy >= node.y && cy <= node.y + node.h) {
      found = node;
      break;
    }
  }

  // 根据是否悬停在节点上改变光标样式
  dom.canvas.style.cursor = found ? 'pointer' : 'default';

  if (found !== hoveredNode) {
    hoveredNode = found;
    if (tooltipTimer) clearTimeout(tooltipTimer);
    if (found) {
      tooltipTimer = setTimeout(() => showTooltip(found, e.clientX, e.clientY), 200);
    } else {
      hideTooltip();
    }
  }
});

// 初始化 tooltip
initTooltip();

dom.canvas.addEventListener('mouseleave', () => {
  hoveredNode = null;
  dom.canvas.style.cursor = 'default'; // 离开时重置光标
  if (tooltipTimer) clearTimeout(tooltipTimer);
  hideTooltip();
});

// --- Canvas 点击 (事件选择 / 子代理展开) ---
dom.canvas.addEventListener('click', (e) => {
  if (state.viewMode === 'subagent') {
    collapseToGlobal();
    return;
  }

  const rect = dom.canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const dpr = window.devicePixelRatio || 1;

  // 关键修复：必须除以DPR，与mousemove保持一致
  const scaleX = (dom.canvas.width / dpr) / rect.width;
  const scaleY = (dom.canvas.height / dpr) / rect.height;
  const cx = mx * scaleX;
  const cy = my * scaleY;

  if (!state.timeline) return;
  const layout = computeLayout(state.timeline, dom.canvas.width / dpr);

  // 点击子代理节点 -> 展开
  for (const node of layout.allNodes) {
    if (node.type === 'subagent_created' || node.type === 'subagent_completed' || node.type === 'subagent_failed') {
      if (cx >= node.x && cx <= node.x + node.w && cy >= node.y && cy <= node.y + node.h) {
        expandSubagent(node.event.agent_id);
        return;
      }
    }
  }

  // 点击普通节点 -> 选中并更新详情
  for (let i = 0; i < layout.allNodes.length; i++) {
    const node = layout.allNodes[i];
    if (cx >= node.x && cx <= node.x + node.w && cy >= node.y && cy <= node.y + node.h) {
      const evt = node.event;

      // 使用多种策略查找事件索引
      let idx = -1;

      // 策略1: 直接引用比较（最快）
      for (let j = 0; j < state.events.length; j++) {
        if (state.events[j] === evt) {
          idx = j;
          break;
        }
      }

      // 策略2: 如果没找到，使用 event_id 匹配
      if (idx < 0 && evt.event_id) {
        for (let j = 0; j < state.events.length; j++) {
          if (state.events[j].event_id === evt.event_id) {
            idx = j;
            break;
          }
        }
      }

      // 策略3: 如果还没找到，使用 event_type + timestamp 匹配
      if (idx < 0) {
        for (let j = 0; j < state.events.length; j++) {
          if (state.events[j].event_type === evt.event_type &&
              state.events[j].timestamp === evt.timestamp) {
            idx = j;
            break;
          }
        }
      }

      // 策略4: 对于 round 节点，尝试匹配 llm_call 或 llm_response 类型
      if (idx < 0 && (node.type === 'round')) {
        for (let j = 0; j < state.events.length; j++) {
          const e = state.events[j];
          if ((e.event_type === 'llm_call' || e.event_type === 'llm_response') &&
              e.timestamp === evt.timestamp) {
            idx = j;
            break;
          }
        }
      }

      // 即使找不到精确索引，也允许选中（使用节点在allNodes中的位置作为备选）
      if (idx < 0) {
        // 尝试找最接近的事件（同类型或相邻）
        idx = Math.min(i, state.events.length - 1);
      }

      // 更新状态
      state.currentIndex = idx;
      state.selectedNodeId = evt.id || evt.event_id || i;
      dom.progressBar.value = idx;
      dom.positionLabel.textContent = '事件 ' + (idx + 1) + ' / ' + state.events.length;
      // 如果是 round 节点，传递完整的节点信息以显示工具调用详情
      if (node.type === 'round' && node.roundTools) {
        updateDetailPanel(state.events[idx], node);
      } else {
        updateDetailPanel(state.events[idx]);
      }
      renderTimeline();

      // 自动滚动到被点击的节点位置，使其居中显示
      const wrapper = document.getElementById('canvasWrapper');
      if (wrapper) {
        const nodeCenterX = node.x + node.w / 2;
        const nodeCenterY = node.y + node.h / 2;
        const targetScrollX = nodeCenterX - wrapper.clientWidth / 2;
        const targetScrollY = nodeCenterY - wrapper.clientHeight / 2;

        wrapper.scrollTo({
          left: Math.max(0, targetScrollX),
          top: Math.max(0, targetScrollY),
          behavior: 'smooth'
        });
      }
      return;
    }
  }
});
