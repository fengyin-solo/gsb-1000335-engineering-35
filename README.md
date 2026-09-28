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

#### 回填修复本地样例

启动脚本会先执行 `python -m app.backfill_seed`，为回填修复模块准备本地样例
（状态文件 `backend/data/backfill.seed`，仅本机使用，已在 `.gitignore` 忽略）：

- **首次运行**：环境检查（目录可建、可写、路径不冲突）通过后，生成 3 条字段
  完整的确定性样例——回填编号、修复路段、管沟深度、回填材料逐条校验，缺任一项
  直接中止，不会落半成品；
- **写入原子化**：先写 `backfill.seed.tmp`、刷盘后再原子替换为正式文件。
  启动时发现遗留 tmp：内容完整则补提交（中断恢复），缺字段则清理后重建；
- **再次运行**：正式文件结构与校验和一致就原样沿用，因此启动、查询、再次运行
  看到的记录完全一致。手工也可执行 `cd backend && python -m app.backfill_seed`
  查看当前属于哪种模式。

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
