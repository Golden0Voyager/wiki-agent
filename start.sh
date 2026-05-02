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

# ── 调色板（v2 极简风：青色品牌 + 软边框） ──────────────────
# 使用 $'…' 让常量保存为真正的 ESC 字符，
# printf / echo / sed 都能直接复用（无需各自再做转义）。
B=$'\033[1m'         # bold
D=$'\033[2m'         # dim
C=$'\033[36m'        # cyan (品牌色)
DC=$'\033[2;36m'     # dim cyan (软边框)
BC=$'\033[1;36m'     # bold cyan (区块标题)
G=$'\033[32m'        # green ✓
Y=$'\033[33m'        # yellow ›
R=$'\033[31m'        # red ✗
NC=$'\033[0m'

# ── 工具函数 ──────────────────────────────────────────────

# 行内状态日志：dim 前缀，配 ✓/›/✗ 状态符
_log() { printf "  ${D}›${NC} %b\n" "$*"; }
_ok()  { printf "  ${G}✓${NC} %b\n" "$*"; }
_warn(){ printf "  ${Y}!${NC} %b\n" "$*"; }
_err() { printf "  ${R}✗${NC} %b\n" "$*"; }

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
    printf "\n  ${B}wikiagent${NC} ${D}— starting${NC}\n\n"

    local vector_dur="-" api_dur="-"

    # 1. 启动 Vector Service (加载模型最慢，优先启动)
    if _is_running "vector_service"; then
        _warn "vector 已在运行 ${D}(PID $(cat "$PID_DIR/vector_service.pid"))${NC}"
    else
        cd "$PROJECT_DIR"
        nohup .venv/bin/python -u scripts/vector_service.py \
            > "$LOG_DIR/vector_service.log" 2>&1 &
        echo $! > "$PID_DIR/vector_service.pid"
    fi

    # 2. 等待 Vector Service 就绪
    local t0=$SECONDS
    for i in $(seq 1 60); do
        if curl -s http://127.0.0.1:8001/search -X POST \
            -H "Content-Type: application/json" \
            -d '{"query":"test","k":1}' -o /dev/null 2>/dev/null; then
            vector_dur="$((SECONDS - t0))s"
            break
        fi
        if [ "$i" -eq 60 ]; then
            _err "vector 启动超时，详见 ${D}$LOG_DIR/vector_service.log${NC}"
            return 1
        fi
        sleep 2
    done

    # 3. 启动 Uvicorn API 后端
    if _is_running "uvicorn"; then
        _warn "api 已在运行 ${D}(PID $(cat "$PID_DIR/uvicorn.pid"))${NC}"
    else
        cd "$PROJECT_DIR"
        nohup uv run uvicorn api:app --host 127.0.0.1 --port 8000 \
            > "$LOG_DIR/uvicorn.log" 2>&1 &
        echo $! > "$PID_DIR/uvicorn.pid"
    fi

    # 4. 等待 API 就绪
    t0=$SECONDS
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:8000/docs -o /dev/null 2>/dev/null; then
            api_dur="$((SECONDS - t0))s"
            break
        fi
        if [ "$i" -eq 30 ]; then
            _err "api 启动超时，详见 ${D}$LOG_DIR/uvicorn.log${NC}"
            return 1
        fi
        sleep 2
    done

    # 5. 启动 Directory Watcher
    if _is_running "watcher"; then
        _warn "watcher 已在运行 ${D}(PID $(cat "$PID_DIR/watcher.pid"))${NC}"
    else
        cd "$PROJECT_DIR"
        nohup .venv/bin/python -u scripts/watcher.py \
            > "$LOG_DIR/watcher.log" 2>&1 &
        echo $! > "$PID_DIR/watcher.pid"
    fi

    # ── 总览面板 ─────────────────────────────────────────
    echo ""
    printf "${DC}╭─${NC} ${BC}wikiagent${NC} ${DC}──────────────────────────────────────────╮${NC}\n"
    printf "${DC}│${NC}                                                          ${DC}│${NC}\n"
    printf "${DC}│${NC}   ${G}✓${NC}  ${B}vector${NC}    ${D}:8001${NC}    ready    ${D}%-6s${NC}                ${DC}│${NC}\n" "$vector_dur"
    printf "${DC}│${NC}   ${G}✓${NC}  ${B}api${NC}       ${D}:8000${NC}    ready    ${D}%-6s${NC}                ${DC}│${NC}\n" "$api_dur"
    printf "${DC}│${NC}   ${G}✓${NC}  ${B}watcher${NC}            monitoring ${C}incoming/${NC}              ${DC}│${NC}\n"
    printf "${DC}│${NC}                                                          ${DC}│${NC}\n"
    printf "${DC}╰──────────────────────────────────────────────────────────╯${NC}\n\n"

    printf "${DC}╭─${NC} ${BC}endpoints${NC} ${DC}──────────────────────────────────────────╮${NC}\n"
    printf "${DC}│${NC}  ${B}api${NC}        ${C}http://127.0.0.1:8000${NC}                       ${DC}│${NC}\n"
    printf "${DC}│${NC}  ${B}search${NC}     ${C}http://127.0.0.1:8001/search${NC}                ${DC}│${NC}\n"
    printf "${DC}│${NC}  ${B}docs${NC}       ${D}incoming/${NC}                                   ${DC}│${NC}\n"
    printf "${DC}│${NC}  ${B}ingest${NC}     ${D}wiki/log.md${NC}                                 ${DC}│${NC}\n"
    printf "${DC}╰──────────────────────────────────────────────────────────╯${NC}\n\n"

    printf "  ${D}./start.sh   ${C}stop${NC} ${D}·${NC} ${C}status${NC} ${D}·${NC} ${C}logs${NC}\n\n"
}

# ── 停止 ──────────────────────────────────────────────────

do_stop() {
    printf "\n  ${B}wikiagent${NC} ${D}— stopping${NC}\n\n"

    for service in uvicorn watcher vector_service; do
        if _is_running "$service"; then
            local pid
            pid=$(cat "$PID_DIR/$service.pid")
            kill "$pid" 2>/dev/null || true
            rm -f "$PID_DIR/$service.pid"
            _ok "$service ${D}stopped (PID $pid)${NC}"
        else
            _warn "$service ${D}not running${NC}"
        fi
    done

    echo ""
}

# ── 状态 ──────────────────────────────────────────────────

do_status() {
    echo ""
    printf "${DC}╭─${NC} ${BC}services${NC} ${DC}───────────────────────────────────────────╮${NC}\n"
    for service in uvicorn vector_service watcher; do
        if _is_running "$service"; then
            local pid
            pid=$(cat "$PID_DIR/$service.pid")
            printf "${DC}│${NC}  ${G}✓${NC}  ${B}%-16s${NC}  running       ${D}PID %-7s${NC}      ${DC}│${NC}\n" "$service" "$pid"
        else
            printf "${DC}│${NC}  ${R}✗${NC}  ${B}%-16s${NC}  ${D}stopped${NC}                            ${DC}│${NC}\n" "$service"
        fi
    done
    printf "${DC}╰──────────────────────────────────────────────────────────╯${NC}\n\n"

    # 知识库统计
    local entity_count concept_count source_count total_count
    entity_count=$(find "$PROJECT_DIR/wiki/entities" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    concept_count=$(find "$PROJECT_DIR/wiki/concepts" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    source_count=$(find "$PROJECT_DIR/wiki/sources" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    total_count=$(( entity_count + concept_count + source_count ))

    printf "${DC}╭─${NC} ${BC}knowledge${NC} ${DC}──────────────────────────────────────────╮${NC}\n"
    printf "${DC}│${NC}  ${B}entities${NC}    ${C}%-44s${NC}  ${DC}│${NC}\n" "$entity_count"
    printf "${DC}│${NC}  ${B}concepts${NC}    ${C}%-44s${NC}  ${DC}│${NC}\n" "$concept_count"
    printf "${DC}│${NC}  ${B}sources${NC}     ${C}%-44s${NC}  ${DC}│${NC}\n" "$source_count"
    printf "${DC}│${NC}  ${B}total${NC}       ${D}%-44s${NC}  ${DC}│${NC}\n" "$total_count"
    printf "${DC}╰──────────────────────────────────────────────────────────╯${NC}\n\n"

    # 最近摄入记录（仅取最后 5 条，剥掉前缀 "- " 后软化为列表）
    printf "  ${BC}recent ingest${NC}\n\n"
    if [ -f "$PROJECT_DIR/wiki/log.md" ]; then
        tail -5 "$PROJECT_DIR/wiki/log.md" | sed -E "s/^- /   ${D}·${NC} /" 2>/dev/null
    else
        printf "   ${D}(暂无记录)${NC}\n"
    fi
    echo ""
}

# ── 日志 ──────────────────────────────────────────────────

do_logs() {
    printf "\n  ${B}wikiagent${NC} ${D}— logs (Ctrl+C 退出)${NC}\n"
    printf "  ${DC}─────────────────────────────────────${NC}\n\n"
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
