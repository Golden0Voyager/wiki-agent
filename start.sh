#!/usr/bin/env bash
# ============================================================
# WikiAgent Knowledge Base — 一键启动 / 停止脚本
# 用法:
#   ./start.sh          启动所有服务
#   ./start.sh stop     停止所有服务
#   ./start.sh status   查看运行状态
#   ./start.sh logs     实时查看合并日志
# ============================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/.pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── 工具函数 ──────────────────────────────────────────────

_log() { echo -e "${BLUE}[WikiAgent]${NC} $*"; }
_ok()  { echo -e "${GREEN}[WikiAgent]${NC} ✅ $*"; }
_warn(){ echo -e "${YELLOW}[WikiAgent]${NC} ⚠️  $*"; }
_err() { echo -e "${RED}[WikiAgent]${NC} ❌ $*"; }

_is_running() {
    local pidfile="$PID_DIR/$1.pid"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# ── 启动 ──────────────────────────────────────────────────

do_start() {
    _log "正在启动 WikiAgent Knowledge Base..."
    _log "项目目录: $PROJECT_DIR"
    echo ""

    # 1. 启动 Vector Service (加载模型最慢，优先启动)
    if _is_running "vector_service"; then
        _warn "Vector Service 已在运行中 (PID: $(cat "$PID_DIR/vector_service.pid"))"
    else
        _log "🚀 启动 Vector Service (port 8001, 加载 bge-m3)..."
        cd "$PROJECT_DIR"
        nohup .venv/bin/python scripts/vector_service.py \
            > "$LOG_DIR/vector_service.log" 2>&1 &
        echo $! > "$PID_DIR/vector_service.pid"
        _ok "Vector Service 已启动 (PID: $!)"
    fi

    # 2. 等待 Vector Service 就绪
    _log "⏳ 等待 Vector Service 加载模型就绪..."
    for i in $(seq 1 60); do
        if curl -s http://127.0.0.1:8001/search -X POST \
            -H "Content-Type: application/json" \
            -d '{"query":"test","k":1}' -o /dev/null 2>/dev/null; then
            _ok "Vector Service 已就绪"
            break
        fi
        if [ "$i" -eq 60 ]; then
            _err "Vector Service 启动超时，请检查 $LOG_DIR/vector_service.log"
            return 1
        fi
        sleep 2
    done

    # 3. 启动 Uvicorn API 后端
    if _is_running "uvicorn"; then
        _warn "Uvicorn API 已在运行中 (PID: $(cat "$PID_DIR/uvicorn.pid"))"
    else
        _log "🚀 启动 Uvicorn API 后端 (port 8000)..."
        cd "$PROJECT_DIR"
        nohup uv run uvicorn api:app --host 127.0.0.1 --port 8000 \
            > "$LOG_DIR/uvicorn.log" 2>&1 &
        echo $! > "$PID_DIR/uvicorn.pid"
        _ok "Uvicorn API 已启动 (PID: $!)"
    fi

    # 4. 等待 API 就绪
    _log "⏳ 等待 API 服务就绪..."
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:8000/docs -o /dev/null 2>/dev/null; then
            _ok "API 服务已就绪"
            break
        fi
        if [ "$i" -eq 30 ]; then
            _err "API 服务启动超时，请检查 $LOG_DIR/uvicorn.log"
            return 1
        fi
        sleep 2
    done

    # 5. 启动 Directory Watcher
    if _is_running "watcher"; then
        _warn "Directory Watcher 已在运行中 (PID: $(cat "$PID_DIR/watcher.pid"))"
    else
        _log "🚀 启动 Directory Watcher (监控 incoming/)..."
        cd "$PROJECT_DIR"
        nohup .venv/bin/python scripts/watcher.py \
            > "$LOG_DIR/watcher.log" 2>&1 &
        echo $! > "$PID_DIR/watcher.pid"
        _ok "Directory Watcher 已启动 (PID: $!)"
    fi

    echo ""
    _ok "══════════════════════════════════════════════"
    _ok "  WikiAgent Knowledge Base 已全部启动！"
    _ok "══════════════════════════════════════════════"
    echo ""
    _log "📡 API 地址:         http://127.0.0.1:8000"
    _log "🔍 向量检索:         http://127.0.0.1:8001/search"
    _log "📁 知识库目录:       $PROJECT_DIR/wiki/"
    _log "📥 文档投递口:       $PROJECT_DIR/incoming/"
    _log "📋 摄入日志:         $PROJECT_DIR/wiki/log.md"
    _log "🔍 服务日志:         $LOG_DIR/"
    echo ""
    _log "💡 使用方法:"
    _log "   投递文档:  将 PDF 放入 incoming/，watcher 会自动处理"
    _log "   手动整理:  uv run python scripts/ingest_documents.py"
    _log "   向量检索:  uv run python scripts/query_kb.py '量子计算'"
    _log "   RAG 问答:  uv run python scripts/rag_qa.py"
    _log "   查看状态:  ./start.sh status"
    _log "   查看日志:  ./start.sh logs"
    _log "   停止服务:  ./start.sh stop"
}

# ── 停止 ──────────────────────────────────────────────────

do_stop() {
    _log "正在停止 WikiAgent Knowledge Base..."

    for service in uvicorn watcher vector_service; do
        if _is_running "$service"; then
            local pid
            pid=$(cat "$PID_DIR/$service.pid")
            kill "$pid" 2>/dev/null || true
            rm -f "$PID_DIR/$service.pid"
            _ok "$service 已停止 (PID: $pid)"
        else
            _warn "$service 未在运行"
        fi
    done

    _ok "所有服务已停止"
}

# ── 状态 ──────────────────────────────────────────────────

do_status() {
    echo ""
    _log "══════════════ 服务状态 ══════════════"

    for service in uvicorn vector_service watcher; do
        if _is_running "$service"; then
            local pid
            pid=$(cat "$PID_DIR/$service.pid")
            echo -e "  ${GREEN}●${NC} $service — 运行中 (PID: $pid)"
        else
            echo -e "  ${RED}●${NC} $service — 已停止"
        fi
    done

    echo ""

    # 知识库统计
    local entity_count concept_count source_count
    entity_count=$(find "$PROJECT_DIR/wiki/entities" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    concept_count=$(find "$PROJECT_DIR/wiki/concepts" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    source_count=$(find "$PROJECT_DIR/wiki/sources" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

    _log "══════════════ 知识库统计 ══════════════"
    echo "  📂 实体卡片:  $entity_count"
    echo "  📂 概念卡片:  $concept_count"
    echo "  📂 来源页面:  $source_count"
    echo "  📊 总计:      $(( entity_count + concept_count + source_count )) 份"
    echo ""

    # 最近摄入记录
    _log "══════════════ 最近摄入 ══════════════"
    tail -5 "$PROJECT_DIR/wiki/log.md" 2>/dev/null || echo "  (暂无记录)"
    echo ""
}

# ── 日志 ──────────────────────────────────────────────────

do_logs() {
    _log "实时合并日志 (Ctrl+C 退出)"
    echo "────────────────────────────────────────"
    local log_files=()
    for svc in uvicorn vector_service watcher; do
        local f="$LOG_DIR/$svc.log"
        [ -f "$f" ] && log_files+=("$f")
    done
    if [ ${#log_files[@]} -eq 0 ]; then
        _warn "暂无日志文件"
        return
    fi
    tail -f "${log_files[@]}" 2>/dev/null
}

# ── 入口 ──────────────────────────────────────────────────

case "${1:-start}" in
    start)  do_start ;;
    stop)   do_stop ;;
    status) do_status ;;
    logs)   do_logs ;;
    *)
        echo "用法: $0 {start|stop|status|logs}"
        exit 1
        ;;
esac
