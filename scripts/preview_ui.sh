#!/usr/bin/env bash
# preview_ui.sh — 极简风 UI 预览 v2 (软边框 + 单一品牌色)

# ── 调色板 ─────────────────────────────────────────
B='\033[1m'        # bold
D='\033[2m'        # dim
C='\033[36m'       # cyan (品牌色)
DC='\033[2;36m'    # dim cyan (软边框)
BC='\033[1;36m'    # bold cyan (区块标题)
G='\033[32m'       # green ✓
Y='\033[33m'       # yellow ›
R='\033[31m'       # red ✗
N='\033[0m'

clear

# ─────────────────────────────────────────────────
# Mockup 1 — start.sh 启动 banner
# ─────────────────────────────────────────────────
printf "\n${D}── mockup 1 · start.sh ─────────────────────────────────${N}\n\n"

printf "${DC}╭─${N} ${BC}wikiagent${N} ${DC}──────────────────────────────────────────╮${N}\n"
printf "${DC}│${N}                                                          ${DC}│${N}\n"
printf "${DC}│${N}   ${G}✓${N}  ${B}vector${N}    ${D}:8001${N}    ready    ${D}4.2s${N}                  ${DC}│${N}\n"
printf "${DC}│${N}   ${G}✓${N}  ${B}api${N}       ${D}:8000${N}    ready    ${D}1.1s${N}                  ${DC}│${N}\n"
printf "${DC}│${N}   ${G}✓${N}  ${B}watcher${N}            monitoring ${C}incoming/${N}              ${DC}│${N}\n"
printf "${DC}│${N}                                                          ${DC}│${N}\n"
printf "${DC}╰──────────────────────────────────────────────────────────╯${N}\n\n"

printf "${DC}╭─${N} ${BC}endpoints${N} ${DC}──────────────────────────────────────────╮${N}\n"
printf "${DC}│${N}  ${B}api${N}        ${C}http://127.0.0.1:8000${N}                       ${DC}│${N}\n"
printf "${DC}│${N}  ${B}search${N}     ${C}http://127.0.0.1:8001/search${N}                ${DC}│${N}\n"
printf "${DC}│${N}  ${B}docs${N}       ${D}incoming/${N}                                   ${DC}│${N}\n"
printf "${DC}│${N}  ${B}ingest${N}     ${D}wiki/log.md${N}                                 ${DC}│${N}\n"
printf "${DC}╰──────────────────────────────────────────────────────────╯${N}\n\n"

printf "  ${D}./start.sh   ${C}stop${N} ${D}·${N} ${C}status${N} ${D}·${N} ${C}logs${N}\n\n"

sleep 2

# ─────────────────────────────────────────────────
# Mockup 2 — rag_qa.py 问答交互
# ─────────────────────────────────────────────────
printf "\n${D}── mockup 2 · rag_qa.py ────────────────────────────────${N}\n\n"

printf "${DC}╭─${N} ${BC}wikiagent rag${N} ${DC}──────────────────────────────────────╮${N}\n"
printf "${DC}│${N}  ${B}retrieval${N}    bge-m3 ${D}→${N} chromadb                         ${DC}│${N}\n"
printf "${DC}│${N}  ${B}generation${N}   modelscope (6) ${D}→${N} openrouter (free)        ${DC}│${N}\n"
printf "${DC}│${N}  ${B}exit${N}         ${C}q${N}                                          ${DC}│${N}\n"
printf "${DC}╰──────────────────────────────────────────────────────────╯${N}\n\n"

printf "${BC}›${N} 量子计算最新进展？\n\n"
printf "  ${D}searching${N}     ${C}5 chunks${N} ${D}·${N} ${C}3 sources${N}\n"
printf "  ${D}modelscope${N}    deepseek-v4-flash      2.4s  ${G}✓${N}\n\n"

printf "${DC}╭─${N} ${BC}answer${N} ${DC}─────────────────────────────────────────────╮${N}\n"
printf "${DC}│${N}                                                          ${DC}│${N}\n"
printf "${DC}│${N}  量子计算最新进展包括超导量子比特数量突破、容错量子      ${DC}│${N}\n"
printf "${DC}│${N}  计算的关键里程碑、以及国内厂商在专用领域的产业化落地    ${DC}│${N}\n"
printf "${DC}│${N}                                                          ${DC}│${N}\n"
printf "${DC}╰──────────────────────────────────────────────────────────╯${N}\n\n"

printf "  ${B}sources${N}\n"
printf "   ${D}·${N} ${C}[量子计算_产业政策]_2025_华尔街见闻....pdf${N}\n"
printf "   ${D}·${N} ${C}[量子计算_电子行业]_2025_xxx....pdf${N}\n"
printf "   ${D}·${N} ${C}[量子计算_科技投资]_2025_xxx....pdf${N}\n\n"

printf "${BC}›${N} \n\n"

sleep 2

# ─────────────────────────────────────────────────
# Mockup 3 — query_kb.py 检索结果
# ─────────────────────────────────────────────────
printf "\n${D}── mockup 3 · query_kb.py ──────────────────────────────${N}\n\n"

printf "${DC}╭─${N} ${BC}search${N} ${DC}─────────────────────────────────────────────╮${N}\n"
printf "${DC}│${N}  ${B}量子计算${N}     ${C}5 results${N}                                  ${DC}│${N}\n"
printf "${DC}╰──────────────────────────────────────────────────────────╯${N}\n\n"

printf "  ${BC}1${N}  ${B}0.43${N}   ${C}[量子计算_产业政策]_2025_华尔街见闻_十五五产业洞察.pdf${N}\n"
printf "         ${D}自十五五规划提出以来，量子计算被纳入战略性新兴产业……${N}\n\n"
printf "  ${BC}2${N}  ${B}0.46${N}   ${C}[量子计算_电子行业]_2025_广发证券_量子计算产业化路径.pdf${N}\n"
printf "         ${D}国内厂商在超导量子比特数量上的突破……${N}\n\n"
printf "  ${BC}3${N}  ${B}0.51${N}   ${C}[量子计算_科技投资]_2025_海通证券_量子计算投资机会.pdf${N}\n"
printf "         ${D}从产业链角度看，量子计算上游设备、中游算法平台……${N}\n\n"
printf "  ${BC}4${N}  ${B}0.55${N}   ${C}[量子计算_产业政策]_2025_xxx....pdf${N}\n"
printf "         ${D}从政策面看，多地省级政府已发布量子计算专项扶持文件……${N}\n\n"
printf "  ${BC}5${N}  ${B}0.58${N}   ${C}[量子计算_产业政策]_2025_xxx....pdf${N}\n"
printf "         ${D}专家研讨会指出，国内量子计算面临三大挑战……${N}\n\n"

printf "${D}── end of preview ──────────────────────────────────────${N}\n\n"
