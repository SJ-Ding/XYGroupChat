---
name: family-appointment
description: 一句话查询两院相关科室模拟号源，自动选号并完成模拟挂号，仅在支付前由本人确认。
---

先读取当前可见 memory_search 和 medical_profile 补全患者、科室、日期与时段。明确科室直接查询；症状不明确时追问，不诊断。缺患者必须追问。日期默认未来可用日期、时段优先记忆偏好，其次上午，告知采用的偏好。

`hospital_simulator(action=query, department, date?, preferred_time?, hospital_id?)` 只读查询号源，包含医院标识。仅询问有没有号时返回结果，不办理。用户要求挂号时，按距离、就诊熟悉度、医生连续性、职称的现有排序选可用号源，用 `action=book` 传患者、科室、slot_id、campus_id、doctor_id、date 办理。无需另行选号或子女授权，浏览器每次点击至少间隔3秒，自动锁号后由本人核对支付卡并在模拟收银台付款。

只有 `status` 返回实际预约编号后才能说锁号成功；未付款不得说已付款。重复预约、停诊、约满按实际结果处理，不承诺挂号成功。真实医院名称、地址、坐标来自高德；医生、费用、号源及预约均为模拟演示，不代表真实医院排班。

`action=status` 查询进度；`action=cancel` 仅在明确要求时终止任务。不调用 approve；不代付、不索取账号密码。
