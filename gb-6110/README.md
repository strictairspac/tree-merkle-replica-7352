# 青徊园护·行道树副本点验

巡养终端回网后先比较整段摘要，仅展开存在差异的树号区间。

## 业务流程

1. 巡护交班
2. 双侧养护快照
3. 分段点验
4. 补录核查单

共享主键边界的稀疏 Merkle 树，按区间展开缺行、孤立行和不同版本。

青徊园护的 12 人组用离线终端记录行道树养护。人工点验需要下载两份全量清单，逆序导出会干扰简单文本比较，终端记录较旧时也很难区分业务冲突与滞后修订。上游为主账和同一截止时点的终端快照，下游为负责补录和人工追查的核对员。

08:40 导出 ST-XH-1124 的主侧 48 条、终端 48 条；08:43 核对截止时点；08:45 设置每叶 16 个树号；08:47 比较根与分支摘要；08:50 定位 1234、1259、1260、1281；08:55 人工确认同代冲突；09:00 下载补录核查单；09:15 重跑仅顺序不同的东城对照。

每个叶区间由固定键域推导，输入顺序不影响摘要。叶以按树号排序的规范 JSON 计算 SHA-256，两个子摘要带类型前缀合并为父摘要。只对摘要不同的叶逐键比较。构树会读完双方输入，比较摘要的计数仅表示已建树后的递归比对开销。演练使用同一应用中提供的两份快照，MySQL 保存记录与证据，不连真实主从，也不自动修复终端数据。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18311>。OpenAPI 在 <http://localhost:19311/docs>，数据库映射到本机 17811。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「每个叶区间包含的树号数（1–65536）」、提交、查看和下载结果 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |

选用「ST-XH-1124 / 西河片区」对应的演示资料，保存一份复演资料，再以默认参数 16 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「补录核查单」签署。

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | MySQL 8.0 |
| 后台执行 | Redis 通知、数据库持久任务队列和行锁、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、完成和签署事件写入审计表。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 验收范围

比较同一截止时点的两组快照。差异交接单由下游人员处理。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6110/TESTING.md)。

[MIT License](LICENSE)
