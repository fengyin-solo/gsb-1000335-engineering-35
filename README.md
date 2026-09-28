# 城市地下管网养护管理平台

面向市政供排水、燃气、供热、电力管线等地下管网的普查建档、巡检养护、病害修复、开挖审批与应急抢修的综合管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

#### 回填修复样例引导（本地）

回填修复模块不再使用写死的占位样例，改由 `backend/app/backfill_bootstrap.py` 在
服务启动（lifespan）时引导：

- **环境检查**：启动前校验 Python 版本、样例目录可写、样例模板字段完整
  （回填编号、修复路段、管沟深度、回填材料等缺一不可）；`run.sh` 不通过不启动，
  也可手工跑 `.venv/bin/python -m app.backfill_bootstrap --check`。
- **首次运行**：生成 3 条真实样例，验收日期相对当天计算（不会过期），
  先写临时文件再原子改名落盘到 `backend/data/backfill_samples.json`。
- **中断恢复**：上次写入中断留下临时文件时，先清理半成品再重建，内存整体替换。
- **再次运行**：快照完整且校验和一致则原样加载，因此启动、查询、再次运行
  看到的记录完全一致；快照损坏会备份为 `.corrupt` 后重建。
- 仅在 `APP_ENV` 为 `local`/`dev` 时引导，生产等环境自动跳过；样例目录可用
  环境变量 `BACKFILL_DATA_DIR` 覆盖，默认 `backend/data/`（已加入 `.gitignore`）。

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 管段档案 | `pipe_section` | 管段 | 管段编号、管线类型、材质规格 |
| 巡查记录 | `inspect` | 巡查记录单 | 巡查编号、巡查路段、巡查人员 |
| 病害管理 | `defect` | 病害记录 | 病害编号、关联管段、病害类型 |
| CCTV检测 | `cctv` | 检测报告 | 报告编号、检测管段、检测方式 |
| 阀门管理 | `valve` | 阀门设备 | 阀门编号、阀门类型、口径规格 |
| 养护计划 | `maintenance` | 养护计划 | 计划编号、养护管段、养护类型 |
| 应急抢修 | `emergency` | 抢修任务 | 抢修编号、管道类型、事故地点 |
| 开挖审批 | `excavation` | 开挖申请 | 申请编号、申请单位、施工地点 |
| 井盖管理 | `well` | 检查井 | 井盖编号、井盖类型、所在道路 |
| 排水清疏 | `drainage` | 清疏任务 | 清疏编号、清疏管段、淤积程度 |
| 气体监测 | `gas_detect` | 监测点位 | 点位编号、监测气体、所在管沟 |
| 漏水检测 | `leak` | 漏水记录 | 记录编号、检测管段、检测方法 |
| 水表管理 | `meter_record` | 贸易结算表 | 表具编号、表具类型、口径规格 |
| 消防栓管理 | `hydrant` | 消防栓 | 消防栓编号、口径规格、所在道路 |
| 管沟巡检 | `trench` | 管沟段 | 管沟编号、管沟位置、沟内管线 |
| 占道施工 | `road_occupy` | 占道申请 | 申请编号、施工路段、占道面积 |
| 回填修复 | `backfill` | 回填记录 | 回填编号、修复路段、管沟深度 |
| 防腐检测 | `corrosion` | 防腐记录 | 记录编号、检测管段、防腐层类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
