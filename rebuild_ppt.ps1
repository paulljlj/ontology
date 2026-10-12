$ErrorActionPreference='Stop'
$src=Join-Path (Get-Location) 'Ontology-software.pptx'
$out=Join-Path (Get-Location) 'Ontology-software-restructured.pptx'
$pp=New-Object -ComObject PowerPoint.Application
$pp.Visible=$true
$pres=$pp.Presentations.Open($src,$false,$false,$false)
$pres.SaveAs($out)

function AddText($slide,$x,$y,$w,$h,$txt,$size=22,$color=0x1F2937,$bold=$false){
  $sh=$slide.Shapes.AddTextbox(1,$x,$y,$w,$h)
  $sh.TextFrame.TextRange.Text=$txt
  $sh.TextFrame.TextRange.Font.Size=$size
  $sh.TextFrame.TextRange.Font.Name='Microsoft YaHei'
  $sh.TextFrame.TextRange.Font.Color.RGB=$color
  $sh.TextFrame.TextRange.Font.Bold=$bold
  $sh.TextFrame.WordWrap=-1
  return $sh
}
function AddBox($slide,$x,$y,$w,$h,$txt,$fill=0xEFF6FF,$line=0x2563EB,$size=18){
  $sh=$slide.Shapes.AddShape(5,$x,$y,$w,$h)
  $sh.Fill.ForeColor.RGB=$fill; $sh.Line.ForeColor.RGB=$line; $sh.Line.Weight=1.5
  $sh.TextFrame.TextRange.Text=$txt; $sh.TextFrame.TextRange.Font.Size=$size; $sh.TextFrame.TextRange.Font.Name='Microsoft YaHei'; $sh.TextFrame.TextRange.Font.Color.RGB=0x1F2937; $sh.TextFrame.TextRange.ParagraphFormat.Alignment=2
  $sh.TextFrame.VerticalAnchor=3
  return $sh
}
function AddArrow($slide,$x1,$y1,$x2,$y2){$a=$slide.Shapes.AddConnector(1,$x1,$y1,$x2,$y2);$a.Line.ForeColor.RGB=0x64748B;$a.Line.Weight=2;$a.Line.EndArrowheadStyle=3}
function AddBase($title,$subtitle){$s=$pres.Slides.Add(1,12);$s.Background.Fill.ForeColor.RGB=0xFFFFFF;[void](AddText $s 45 25 840 45 $title 28 0x0F3B66 $true);[void](AddText $s 48 75 840 30 $subtitle 13 0x64748B);return $s}

# 1 opening
$s=AddBase '重构版｜Ontology 本体智能体与代码实现' '先回答“本体智能体是什么”，再回答“我们如何把它写出来”'
AddBox $s 85 180 330 125 '第一部分`n本体智能体是什么' 0xE8F3FF 0x2563EB 24
AddBox $s 535 180 330 125 '第二部分`n我们的代码开发工作' 0xECFDF5 0x16A34A 24
AddArrow $s 415 242 535 242
AddText $s 170 360 650 60 '核心主线：AI 负责生成与决策，本体负责语义约束与合法性判断' 20 0x334155 $true

# 2 why
$s=AddBase '第一部分｜为什么需要本体智能体' '从 LLM 的能力边界，引出本体的约束价值'
AddBox $s 70 155 235 115 'LLM / Agent' 0xFFF7ED 0xEA580C 22
AddText $s 83 225 210 45 '理解需求、生成方案、调用工具' 14 0x7C2D12
AddBox $s 375 155 235 115 '风险' 0xFEF2F2 0xDC2626 22
AddText $s 392 225 200 45 '幻觉、脏数据、规则绕过' 14 0x7F1D1D
AddBox $s 680 155 235 115 'Ontology' 0xEFF6FF 0x2563EB 22
AddText $s 695 225 205 45 '知识、关系、公理、约束' 14 0x1E3A8A
AddArrow $s 305 212 375 212; AddArrow $s 610 212 680 212
AddText $s 130 345 720 90 '本体智能体 = Agent 的自主执行能力 + 本体的语义约束能力' 26 0x0F3B66 $true

# 3 definition/layers
$s=AddBase '本体智能体是什么' '把静态知识变成可执行、可校验、可推理的智能系统'
AddBox $s 120 145 700 70 '动态层｜Agent 决策与行动' 0xDBEAFE 0x2563EB 22
AddBox $s 120 230 700 70 '行为层｜流程、规则与工具调用' 0xE0F2FE 0x0284C7 22
AddBox $s 120 315 700 70 '语义层｜Class、Instance、Relation、Property' 0xECFDF5 0x16A34A 22
AddText $s 175 425 600 60 '三层关系：语义层定义“是什么” → 行为层定义“如何运作” → 动态层决定“怎么行动”' 18 0x334155

# 4 workflow
$s=AddBase '本体智能体的工作流程' '一次请求如何从自然语言走向合法入库'
$labels=@('用户需求','Agent 理解\n与任务规划','MCP 工具\n调用','本体校验\n与推理','通过：写入\n系统','失败：返回错误\n并重试')
$xs=@(45,195,345,495,645,795)
for($i=0;$i -lt $labels.Count;$i++){AddBox $s $xs[$i] 190 125 90 $labels[$i] 0xF8FAFC 0x64748B 16;if($i -lt 5){AddArrow $s ($xs[$i]+125) 235 ($xs[$i+1]) 235}}
AddText $s 150 350 670 80 'ReAct 闭环：Reasoning（思考）→ Acting（行动）→ Observation（反馈）→ 修正' 22 0x0F3B66 $true

# 5 technology map
$s=AddBase '本体智能体的技术组成' '四个层次共同构成“可控的 Agent”'
AddBox $s 70 150 180 120 '本体层\nOWL / 类 / 关系\n公理与约束' 0xECFDF5 0x16A34A 18
AddBox $s 285 150 180 120 '推理校验层\nReasoner / Pellet\n冲突检测与推导' 0xEFF6FF 0x2563EB 18
AddBox $s 500 150 180 120 'Agent 层\nLLM / Memory\nPlanning / ReAct' 0xFFF7ED 0xEA580C 18
AddBox $s 715 150 180 120 '工具层\nMCP\n查询与写入能力' 0xF5F3FF 0x7C3AED 18
AddArrow $s 250 210 285 210;AddArrow $s 465 210 500 210;AddArrow $s 680 210 715 210
AddText $s 145 345 700 70 '关键原则：工具可以被调用，但写入必须通过本体校验' 24 0x0F3B66 $true

# 6 example
$s=AddBase '贯穿示例｜Feature 到 Task 的语义链路' '用软件工程对象解释本体如何组织知识与约束行为'
$labels=@('Feature\n需求目标','Spec\n功能规格','Plan\n技术方案','Task\n实现步骤')
$xs=@(75,295,515,735)
for($i=0;$i -lt 4;$i++){AddBox $s $xs[$i] 175 160 100 $labels[$i] 0xEFF6FF 0x2563EB 18;if($i -lt 3){AddArrow $s ($xs[$i]+160) 225 ($xs[$i+1]) 225}}
AddText $s 105 330 760 90 '本体约束示例：Spec 必须归属于 Feature；Task 必须关联 Plan；非法关系不能入库。' 20 0x334155

# 7 divider before existing content
$s=AddBase '第二部分｜我们的代码开发工作' '从概念进入工程：模型、流程、存储、MCP 与验证'
AddText $s 145 205 700 150 '我们不是只定义本体，\n而是把本体接入完整的软件工程系统。' 30 0x0F3B66 $true
AddText $s 175 405 650 50 '后续页面保留原有代码、架构和实现说明，作为工程落地部分。' 18 0x64748B

# 8 roadmap
$s=AddBase '代码开发部分的阅读顺序' '让实现内容对应前面的理论概念'
$items=@('本体模型与领域数据结构','AI 工作流：Feature → Spec → Plan → Task','OWL / Pellet 推理与语义校验','PostgreSQL + Neo4j 双存储','MCP Agent 受控调用','项目验证、贡献与展望')
for($i=0;$i -lt 6;$i++){ $col=$i%3; $row=[math]::Floor($i/3); AddBox $s (90+$col*285) (160+$row*145) 240 90 ('0'+($i+1)+'｜'+$items[$i]) 0xF8FAFC 0x0EA5E9 16 }

$pres.Save()
$pres.Close();$pp.Quit()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($pres)|Out-Null
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($pp)|Out-Null
Write-Output $out
