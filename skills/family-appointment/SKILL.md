---
name: family-appointment
description: 查询两家独立模拟医院的科室号源，先让用户选择医院，再自动选号挂号，支付由本人确认。
---

从当前可见 memory_search 和 medical_profile 补全患者、科室、日期和时段；缺患者或无法对应科室时追问。默认采用记忆偏好，其次未来可用日期、上午，并说明采用的偏好。不诊断。

用户只问有没有号，调用 `hospital_simulator(action=query, department, date?, preferred_time?, hospital_id?)`，只读返回号源和医院目录，不启动挂号。医院名称和 ID 以目录为准，不虚构标识。

用户要求办理时，先展示两家医院供用户选择；用户已经明确指定医院时采用该医院。聊天中的医院选择卡会启动该院流程；网页入口 `/hospital/` 也可选择进入独立应用 `/hospital/apps/{hospital_id}/`。不要把两家医院说成同一家医院的两个院区。所选医院无该科室时说明原因，请用户重新选择；约满时可继续查该院其他日期，不静默换医院。

在选定医院内沿用距离、熟悉度、医生连续性、职称排序，选可用号源，调用 `hospital_simulator(action=book, hospital_id, instruction, department, patient_name, slot_id, campus_id, doctor_id, date)`。工具返回 awaiting_hospital_selection 时先等待用户选择，不宣称已经开始。浏览器自动在该医院应用代填并锁号，点击间隔至少1.5秒，不需要子女授权。

用 `action=status` 查实际进度；只有实际返回预约编号才说锁号成功。锁号后本人在该院模拟收银台核对付款；未支付不说已支付。不调用 approve、不代付。仅在用户明确要求时用 `action=cancel` 终止任务。

医院名称、地址、坐标来自高德；医生、患者、费用、号源、支付和预约是模拟演示，不代表真实医院排班。预约草稿、号源和记录按医院隔离，历史支付链接自动回到所属医院。
