# VRT、MOD、SMCI：业务与 AI 基建合作核验

检索日期：2026-09-26，北京时间（UTC+8）；本轮于 17:17 后整理。研究范围：美国上市公司业务、已公开合作与未来交付，不含股价、估值或买卖时点建议。金额均为美元。本文是时点报告，不自动更新。

## 结论摘要

三家都与 AI 基建有实际业务联系，但不是三家同质的“液冷公司”：VRT 提供供电、散热和配套服务；MOD 通过 Airedale 提供冷却设备；SMCI 提供服务器、机柜和液冷集成系统。没有证据把它们的相关收入全部归因于视频生成，也未确认它们与 Seedance 有直接采购关系。

合作必须区分：**已部署案例、已宣布订单、已签产能协议、MOU/渠道合作、技术联合开发**。已宣布合作不等于全部交付，产能协议和 MOU 金额也不等于已确认收入。

## 一、VRT：供电与散热基础设施商

### 业务与 AI 的关系

VRT 的产品包括 UPS、配电、开关设备、母线、风冷与液冷、模块化基础设施、机柜、监控及服务。AI 高密度机柜同时增加供电、排热和系统集成要求，因此它可以在同一项目中提供多个环节。它不是 GPU 厂商，也不是出租 GPU 的云平台。公司按地区报告分部，不能直接从总收入读出“AI 液冷收入占比”。[1：VRT 10-Q，报告期 2026-06-30、申报日 2026-07-29](https://www.sec.gov/Archives/edgar/data/1674101/000162828026050609/vrt-20260630.htm)

### 已公开的具体合作

| 对象 | 做什么 | 证据状态与边界 |
| --- | --- | --- |
| CoreWeave，与 Dell 等共同参与 | 为 GB300 NVL72 部署提供 CoolChip CDU 液冷系统和工程支持 | **已部署案例**；客户和平台明确，金额及后续新增订单未披露。不是 CoreWeave 全部数据中心的独家供货证明。[2：官方案例，2025 年发布，地区页面日期格式有歧义，不据此确定具体月日](https://www.vertiv.com/tr-emea/about/news-and-events/articles/blog-posts/how-vertiv-and-coreweave-are-orchestrating-ai-innovation/) |
| 美国海军研究生院 NPS | 为 NVIDIA DGX GB300 系统提供供电、液冷、机柜及安装服务 | **2026-07-23 公告部署**；是具名 AI 计算项目，但不能与超大规模商业园区等量齐观。[3：项目公告](https://www.vertiv.com/en-ca/about/news-and-events/corporate-news/2026/vertiv-infrastructure-helps-bring-nvidia-ai-computing-capability-to-the-naval-postgraduate-school/) |
| Hut 8 | 将 OneCore 一体化基础设施纳入部分数据中心项目，整合供电、散热和数字化设计 | **2026-02-26 公布项目合作**；具体采购金额和全面交付进度未披露，不自行对应到某个园区全部订单。[4：合作公告](https://www.vertiv.com/en-in/about/news-and-events/news-releases/2026/vertiv-industrializes-ai-deployment-with-digitally-orchestrated-infrastructure-collaborates-with-hut-8-to-scale/) |

### 未来机会：已经宣布，但收入待验证

**NVIDIA Vera Rubin DSX：**2026-03-16 公告参与供电、散热和数字孪生参考设计。分析推断：进入架构设计阶段可能提高后续项目采用机会，但参考设计不是 NVIDIA 或云厂商的采购订单。[5：官方公告](https://www.vertiv.com/en-asia/about/news-and-events/news-releases/2026/vertiv-brings-converged-physical-infrastructure-to-nvidia-vera-rubin-dsx-ai-factories/)

**Generate Capital：**2026-03-04 宣布合作，VRT 提供电力和冷却基础设施，Generate 提供融资、资产持有与运营能力，面向电网接入受限的数据中心。属于已宣布的商业合作模式，公告没有给出可据以计算收入的具名终端订单。[6：官方公告](https://investors.vertiv.com/news/news-details/2026/Vertiv-and-Generate-Capital-Collaborate-to-Accelerate-Data-Center-Capacity-with-Complete-Power-and-Cooling-Infrastructure/)

### 财务兑现与风险

2026 年第二季度总收入约 **32.74 亿**、同比增长 **24%**，GAAP 营业利润约 **6.38 亿**。这些是公司整体结果，并非上述项目或液冷业务独立贡献；财报也提到供应链拥堵和分阶段项目执行对交付时点的影响。[7：2026-07-29 业绩公告，SEC 附件](https://www.sec.gov/Archives/edgar/data/1674101/000162828026050323/q22026exhibit991vrt07292026.htm)

**分析判断：**VRT 比较贴近“AI 基建整体扩容”的研究方向。重点跟踪订单兑现、项目延期、产能扩张以及现金流，不能把参与 NVIDIA 生态等同于拥有 NVIDIA 式的利润结构。

## 二、MOD：数据中心冷却设备，扩产与利润兑现是关键

### 业务与 AI 的关系

Airedale by Modine 提供冷水机组、精密空调/空气处理设备、风墙、列间冷却、CDU 和控制系统。它不只是“传统空调”，也覆盖高密度机柜液冷的换热和循环环节；但不是服务器或 GPU 厂商。[8：官方产品目录](https://www.airedale.com/data-centers/products/)、[9：CDU 产品说明](https://www.airedale.com/data-centers/liquid-cooling/cdu/)（产品页面检索于 2026-09-26，未见统一发布日期）

### 已有订单与未来合作

| 合作 | 已披露事实 | 不能据此认定什么 |
| --- | --- | --- |
| 未具名 AI 基础设施开发商 | 2025-02-27 宣布 **1.8 亿**冷却系统订单，原计划 2025 年至 2026 年上半年交付。[10：订单公告](https://investors.modine.com/news/news-details/2025/Modine-Secures-180-Million-in-Orders-for-Data-Center-Cooling-Systems/default.aspx) | 计划交付窗口已过，不代表本次已核实全部交付；不能猜测客户是 xAI、OpenAI 或字节。 |
| 未具名战略数据中心客户，长期产能协议 | 2026-05-26 公告保障 **2027—2029 年超过 40 亿**冷却产品的供货产能，并收到 **1.65 亿预付款**。[11：协议公告](https://investors.modine.com/news/news-details/2026/Modine-Announces-Landmark-4-Billion-Long-Term-Capacity-Agreement-through-2029-with-Strategic-Data-Center-Customer-for-Airedale-by-Modine-Cooling-Solutions/default.aspx) | 不是已经赚到 40 亿，也不是保证每年平均确认同等收入；不能默认与前一订单为同一家客户。 |

SEC 季报进一步说明：长期产能协议在 **2026 年 3 月签订**，1.65 亿预付款列在合同负债相关披露中。因此，签约时间与 5 月公告时间应分开，预收款不等于利润。季报还显示，截至 6 月的季度数据中心分部收入 **3.486 亿、同比增长约 90%**，毛利率却降至 **20.2%**，反映扩产、成本及执行压力。[12：MOD 10-Q，2026-06-30 报告期，Note 3 与分部经营讨论](https://www.sec.gov/Archives/edgar/data/67347/000110465926088569/mod-20260630x10q.htm)

**分析判断：**MOD 的看点不是猜客户名称，而是验证未来产能承诺是否转成实际采购、交付及利润。收入增长与毛利率下降并存，说明订单多不代表利润同步高速增长。本次没有取得新的具名“正在洽谈”项目证据。

## 三、SMCI：AI 服务器与液冷系统集成，不是纯散热标的

### 业务与 AI 的关系

SMCI 把处理器、GPU、内存、存储、网络、机柜及冷却系统集成为可部署的 IT 方案。它的核心是服务器和系统交付；DLC 液冷与 DCBBS 模块化方案帮助承接更大范围的部署，不应把整台服务器收入全部归为散热收入。[13：SMCI 官方业务与方案说明，2025-05-16](https://ir.supermicro.com/news/news-details/2025/Supermicro-Announces-Strategic-Partnership-with-DataVolt/)

### 已落地与预期合作

| 对象 | 项目内容 | 状态与待验证事项 |
| --- | --- | --- |
| xAI Colossus | 液冷 GPU 服务器，以及冷板、管路、CDU 等配套 | **已有部署案例**。不能把既有合作外推成所有扩建阶段都由 SMCI 承包；项目收入及后续新增订单未独立披露。[14：官方案例，页面未提供明确发布日期，2026-09-26 检索](https://learn-more.supermicro.com/data-center-stories/how-supermicro-built-the-xai-colossus-supercomputer?hs_amp=true) |
| Cisco Secure AI Factory with NVIDIA | Cisco 渠道销售 SMCI 高密度风冷、液冷计算系统 | **2026-08-25 已宣布，计划 2026 年 10 月开始提供**。合作方 Cisco 也确认该时间；截至本报告日期仍是未来计划，且不是具名终端客户已采购的证明。[15：Cisco 公告](https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m08/cisco-secure-ai-factory-nvidia-rack-scale.html)、[16：Cisco FAQ](https://www.cisco.com/c/en/us/solutions/collateral/artificial-intelligence/cisco-secure-ai-factory-nvidia-rackscale-faq.html) |
| DataVolt | 最初面向沙特超大规模 AI 园区，规划 GPU、存储、机柜和液冷方案 | **2025-05-16 公告 MOU**，所涉产品估计最低市场价值 **200 亿**，公告明确仍须谈判并完成正式协议。不能当作 200 亿确定订单。本次未找到足以确认全部转为正式采购的后续披露。[13：SMCI 原始公告](https://ir.supermicro.com/news/news-details/2025/Supermicro-Announces-Strategic-Partnership-with-DataVolt/) |

**更正此前表述：**DataVolt 的“200 亿合作”应表述为带有后续谈判条件的 MOU，而不是已经确定交付的销售合同。这也不证明双方今天仍在谈判；只能说明本次可核实的原始公告具有该条件。

### 财务与治理风险

截至 2026-06-30 的 FY2026 年度收入约 **390.63 亿**。2026-08-31 年报显示，三项此前内控重大缺陷已修复，但 IT 一般控制缺陷仍未修复，期末财务报告内部控制仍被认定无效。审计师对财务报表出具无保留意见、对内部控制出具否定意见；两者不可混淆。[17：SMCI FY2026 10-K，业务、财务及 Item 9A](https://www.sec.gov/Archives/edgar/data/1375365/000137536526000022/smci-20260630.htm)

**分析判断：**SMCI 更直接受益于 AI 服务器交付量，但评估它必须同时看毛利、库存、回款、供应链和治理，而不是拿合作规模直接估算净利润。Cisco 是近期可验证的渠道催化，DataVolt 则应保留为条件性机会。

## 四、如何对应“视频生成增长”的投资假设

以下是分析推断，不是客户已披露的采购原因：

| 公司 | 视频需求如何可能传导到业务 | 必须观察的验证信号 |
| --- | --- | --- |
| VRT | 更多高功率机柜带来电力、热管理及服务需求 | 新项目采用、实际交付、营业利润及现金流 |
| MOD | 园区扩建或冷却升级带来冷水机组、CDU 等需求 | 产能协议转采购、产能利用、毛利率能否恢复 |
| SMCI | 模型训练和推理增加服务器、机柜系统采购 | Cisco 渠道实际销量、正式采购、毛利与回款 |

不能跳过“视频调用增长 → 算力实际需求 → 新增基建采购 → 供应商收入利润”这些环节。模型效率提高、现有集群余量、客户自建和供应商竞争，都可能削弱传导。三家公司共同暴露于 AI 资本开支周期，不是三份彼此独立的风险。

## 五、方法、信息缺口与后续验证

本次使用 deep-research 流程按合作成熟度分类；业务和财务优先核对 SEC，项目优先核对公司及合作方公告，避免将营销描述直接视作订单。未做财务模型或实时估值；季度与年度、整体收入与分部收入不横向混算。数字采用原币美元，仅做单位转换及四舍五入。

已核对 VRT 2026 年二季度 10-Q、MOD 截至 2026-06-30 的 10-Q、SMCI FY2026 10-K，并阅读具体合作公告。这不是三家公司所有历史合同的穷尽清单，也没有完成所有合同附件的法律审阅。

待验证：VRT 具名项目金额与复购；MOD 匿名客户、旧订单最终交付以及长期协议采购条件；SMCI DataVolt 正式合同、Cisco 10 月实际上市及订单；三家公司视频生成相关收入占比。本次均不补造这些数据。历史部署证明过往合作，不自动证明当前新增订单。

继续跟踪时，应把每条信息更新为“公告日—签约日—交付日—收入确认—回款”，有修订则保留历史版本。所有来源链接已紧邻对应事实，编号仅用于定位；公司公告与 SEC 申报是原始披露，但不等于独立验证了所有前瞻目标。
