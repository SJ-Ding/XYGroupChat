# 医院 v2 与就诊后守护

可代办医院为江苏省人民医院（`h-jsph`）和南京鼓楼医院（`h-glyy`）。医院名称、地址和 POI 来自高德公开数据，并写入医院目录；医生、排班、费用、号源、预约和病历仍是虚构演示数据。

- “帮妈妈挂明天上午骨科的号”：先选择医院，再自动排序选号，以至少 1.5 秒间隔填写预约页面，到核对页等待家人确认；锁号后由本人在所属医院模拟收银台支付。
- “查询骨科号源”：只查询，不办理。`hospital_simulator(action=query)` 支持 department、date、time、preferred_time、hospital_id，返回号源和医院目录，不启动浏览器。
- “按这张药单给妈妈创建提醒”：`family-aftercare` 读取病历/药单图片或文字医嘱，生成待确认守护计划；确认后写入照护事项、医疗档案、打卡和复诊简报。

医院选择入口为 `/hospital/`。独立应用地址为 `/hospital/apps/{hospital_id}/`，对应 API 为 `/api/hospital/apps/{hospital_id}/`。新增按院查号接口：

```text
GET /api/hospital/apps/{hospital_id}/slots?dept=骨科&date=2026-11-01&session=morning
```

每个应用只加载本院号源和预约，后端拒绝跨院预约、查询、支付、取消和病历访问。旧预约继续保留，并标记为 `legacy-hospital`。

病历识图使用 `DEEPSEEK_VISION_MODEL`（留空回退到 `DEEPSEEK_MODEL`）和 `VISION_TIMEOUT`；图片按内容哈希缓存，同一图片不会重复调用模型或重复写入医疗档案。低置信度、非医疗图片、模型未配置或超时不会生成计划。

守护计划统一通过 `POST /api/care/cards/{card_id}/act` 确认。旧 `family-prognosis-guard`、`prognosis_guard` 工具和 `/api/groups/{gid}/prognosis/{key}/act` 已移除。升级时先备份数据库，再清理旧预后卡片、相关提醒和待追问状态，不删除预约、上传图片或其他照护数据。
