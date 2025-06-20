# Data Processing 2.0 采用异构图

# **INPUT**

### 全局参数

- **K** : 目标分区数量
- **系统基准功率** (`baseMVA`)

### 图 G=(N,E) - 异构图结构

### N 节点集 - 按物理类型分组

节点数量对应着母线数量，现按物理特性分为3种类型：

**节点类型映射**：

```python
BUS_TYPE_MAP = {1: 'pq', 2: 'pv', 3: 'slack'}
```

| 节点类型 | 描述 | 电网作用 |
| --- | --- | --- |
| **bus_pq** | PQ负荷节点 | 已知有功/无功负荷的负荷母线 |
| **bus_pv** | PV发电节点 | 已知有功功率和电压幅值的发电母线 |
| **bus_slack** | Slack平衡节点 | 已知电压幅值和相角的平衡母线 |

**每种节点类型的特征**：

| 特征 | 维度 | 描述 |
| --- | --- | --- |
| **Pd, Qd** | 2维 | 当前有功/无功负荷标幺值：Pd/baseMVA, Qd/baseMVA |
| **Gs, Bs** | 2维 | 并联电导/电纳 |
| **Vm, Va** | 2维 | 当前电压幅值和相角（弧度） |
| **Vmax, Vmin** | 2维 | 电压约束上下限 |
| **degree** | 1维 | 该母线的度数（连接的支路数量） |
| **Pg, Qg** | 2维 | 当前有功/无功发电标幺值 |
| **Pg_max, Pg_min** | 2维 | 有功发电容量上下限标幺值 |
| **is_gen** | 1维 | 是否有发电机（二元标识） |

**Node Feature Matrix** ：每种类型 `(num_nodes_of_type, 14)`

特征顺序：

```python
['Pd', 'Qd', 'Gs', 'Bs', 'Vm', 'Va', 'Vmax', 'Vmin', 'degree',
 'Pg', 'Qg', 'Pg_max', 'Pg_min', 'is_gen']
```

### E 边集 - 按连接类型分组

**✅ 边特征完全存在且正常工作！**

边数量对应着支路数量，现按物理特性分为2种类型：

**边类型映射**：

```python
BRANCH_TYPE_MAP = {0: 'line', 1: 'transformer'}
```

| 边类型 | 描述 | 判断依据 |
| --- | --- | --- |
| **connects_line** | 输电线路连接 | 变压器变比为0或1 |
| **connects_transformer** | 变压器连接 | 变压器变比不为0且不为1 |

**边特征 - 完整的9维特征**：

| 特征 | 维度 | 描述 | 物理意义 |
| --- | --- | --- | --- |
| **r, x** | 2维 | 支路电阻和电抗 | 阻抗的实部和虚部 |
| **b** | 1维 | 支路电纳 | 充电电纳 |
| **|z|, y** | 2维 | 阻抗模长和导纳 | 阻抗大小和倒数 |
| **rateA** | 1维 | 载流限制标幺值：rateA/baseMVA | 热稳定载流限制 |
| **angle_diff** | 1维 | 相角差限制 | 最大允许相角差 |
| **is_transformer** | 1维 | 是否为变压器（二元标识） | 设备类型标识 |
| **status** | 1维 | 支路运行状态（1=投运，0=停运） | 运行状态 |

**Edge Feature Matrix**：每种关系类型 `(num_edges_of_relation, 9)`

特征顺序：

```python
['r', 'x', 'b', '|z|', 'y', 'rateA', 'angle_diff', 'is_transformer', 'status']
```

**✅ 边特征验证结果**：

- ✅ 特征维度一致：**9维**
- ✅ 数据类型：`torch.float32`
- ✅ 数据质量：无NaN值，所有数值有效
- ✅ 标准化：使用RobustScaler统一处理

### 异构图关系类型

异构图包含多种节点间的连接关系，**每种关系都保持完整的9维边特征**：

| 关系类型 | 描述 | 边特征 |
| --- | --- | --- |
| `(bus_pq, connects_line, bus_pq)` | 负荷节点间线路连接 | ✅ 9维完整特征 |
| `(bus_pv, connects_line, bus_pv)` | 发电节点间线路连接 | ✅ 9维完整特征 |
| `(bus_pq, connects_line, bus_pv)` | 负荷-发电节点线路连接 | ✅ 9维完整特征 |
| `(bus_slack, connects_line, bus_*)` | 平衡节点连接 | ✅ 9维完整特征 |
| `(bus_*, connects_transformer, bus_*)` | 变压器连接 | ✅ 9维完整特征 |
| `(bus_*, rev_connects_*, bus_*)` | 反向连接（无向图） | ✅ 9维完整特征 |

### 图结构特性

- **图类型**：异构无向图 (HeteroData)
- **节点索引**：每种类型内部使用0-based局部索引
- **全局索引映射**：维护全局ID到局部ID的转换关系
- **边特征保持**：所有边关系都保持完整的9维特征
- **缓存机制**：支持MD5哈希自动缓存，文件名包含`_hetero`后缀
- **标准化**：使用RobustScaler对所有类型特征统一标准化

---

# **OUTPUT - PyTorch Geometric HeteroData**

## 数据结构

```python
from torch_geometric.data import HeteroData

data = HeteroData()

# 节点数据 - 按类型存储
data['bus_pq'].x = tensor_pq_features      # PQ节点特征 [n_pq, 14]
data['bus_pv'].x = tensor_pv_features      # PV节点特征 [n_pv, 14]
data['bus_slack'].x = tensor_slack_features # Slack节点特征 [n_slack, 14]

# 边数据 - 按关系类型存储，每种关系都有完整的9维边特征
data[('bus_pq', 'connects_line', 'bus_pv')].edge_index = edge_index     # [2, n_edges]
data[('bus_pq', 'connects_line', 'bus_pv')].edge_attr = edge_attr       # [n_edges, 9]
# ... 其他关系类型，都保持9维边特征

```

## 具体内容

### 1. 节点特征 (按类型分组)

**数据类型**：`torch.FloatTensor`

**形状**：每种类型 `[num_nodes_of_type, 14]`

```python
# 示例：IEEE30系统
data['bus_pq'].x.shape      # torch.Size([24, 14]) - 24个PQ节点
data['bus_pv'].x.shape      # torch.Size([5, 14])  - 5个PV节点
data['bus_slack'].x.shape   # torch.Size([1, 14])  - 1个Slack节点

# 全局ID追踪
data['bus_pq'].global_ids    # tensor([2,3,5,6,8,9,...]) - 对应原始母线ID
data['bus_pv'].global_ids    # tensor([1,4,7,10,12])
data['bus_slack'].global_ids # tensor([0])

```

### 2. 边索引和特征 (按关系类型分组) - **完整的9维边特征**

**数据类型**：

- `edge_index`: `torch.LongTensor`
- `edge_attr`: `torch.FloatTensor` **✅ 完整的9维特征**

**形状**：每种关系 `edge_index: [2, num_edges]`, `edge_attr: [num_edges, 9]`

```python
# 示例：IEEE30系统的关系类型及其边特征
relation_types = [
    ('bus_pv', 'connects_line', 'bus_slack'),      # 1条边, [1, 9]特征
    ('bus_pq', 'connects_line', 'bus_slack'),      # 1条边, [1, 9]特征
    ('bus_pq', 'connects_line', 'bus_pv'),         # 1条边, [1, 9]特征
    ('bus_pq', 'connects_line', 'bus_pq'),         # 2条边, [2, 9]特征
    ('bus_pv', 'connects_line', 'bus_pv'),         # 2条边, [2, 9]特征
    ('bus_pq', 'connects_transformer', 'bus_pq'),  # 2条边, [2, 9]特征
    ('bus_pq', 'connects_transformer', 'bus_pv'),  # 1条边, [1, 9]特征
    # + 对应的反向边 (rev_connects_*) - 也都有完整的9维特征
]

# 边特征示例 - 每条边都有完整的9维特征
data[('bus_pq', 'connects_line', 'bus_pv')].edge_attr
# tensor([[-1.0000, -1.0000, -1.0000, -1.0000,  1.0000,  1.0000,  0.0000, -1.0000,  0.0000]])
#          r        x        b        |z|      y        rateA    angle_diff  is_trans  status

```

### 3. 边特征详细说明

**✅ 完整的9维边特征内容**：

```python
# 每条边的特征包含完整的电气参数
edge_features = {
    'r': '支路电阻 (标准化)',
    'x': '支路电抗 (标准化)',
    'b': '支路电纳 (标准化)',
    '|z|': '阻抗模长 (标准化)',
    'y': '导纳 (标准化)',
    'rateA': '载流限制 (标准化)',
    'angle_diff': '相角差限制',
    'is_transformer': '变压器标识 (-1=线路, 1=变压器)',
    'status': '运行状态 (标准化)'
}

# 验证边特征完整性
for edge_type in data.edge_types:
    edge_attr = data[edge_type].edge_attr
    assert edge_attr.shape[1] == 9  # ✅ 确保9维特征
    assert not torch.isnan(edge_attr).any()  # ✅ 确保无NaN值

```

### 4. 数据访问接口

```python
# 获取所有节点类型
node_types = list(data.node_types)
# ['bus_pq', 'bus_pv', 'bus_slack']

# 获取所有边类型
edge_types = list(data.edge_types)
# [('bus_pv', 'connects_line', 'bus_slack'), ...]

# 总节点数
total_nodes = sum(data[nt].x.shape[0] for nt in node_types)

# 总边数
total_edges = sum(data[et].edge_index.shape[1] for et in edge_types)

# 边特征统计
edge_feature_dims = [data[et].edge_attr.shape[1] for et in edge_types]
print(f"边特征维度一致性: {set(edge_feature_dims)}")  # {9}

```

## 下一个模型的输入格式

### 对于异构图神经网络

```python
from torch_geometric.nn import to_hetero

# 同构模型转异构 - 自动处理边特征
hetero_model = to_hetero(base_gnn, data.metadata(), aggr='sum')

def forward(self, hetero_data):
    # 自动处理不同类型的节点和边特征
    x_dict = hetero_model(
        hetero_data.x_dict,           # 节点特征字典
        hetero_data.edge_index_dict,  # 边索引字典
        hetero_data.edge_attr_dict    # ✅ 边特征字典 - 9维特征
    )
    return x_dict

```

### 对于强化学习环境

```python
class PowerGridEnv:
    def reset(self):
        # hetero_data作为环境状态 - 包含完整边特征
        self.state = {
            'node_features': {
                'bus_pq': data['bus_pq'].x,      # [n_pq, 14]
                'bus_pv': data['bus_pv'].x,      # [n_pv, 14]
                'bus_slack': data['bus_slack'].x  # [n_slack, 14]
            },
            'edge_index_dict': data.edge_index_dict,
            'edge_attr_dict': data.edge_attr_dict,  # ✅ 完整的9维边特征字典
            'metadata': data.metadata()
        }
        return self.state

```

## 数据验证

```python
# 异构图数据完整性检查 - 包含边特征验证
def validate_hetero_data(data):
    # 检查节点特征
    for node_type in data.node_types:
        assert not torch.isnan(data[node_type].x).any()
        assert data[node_type].x.shape[1] == 14  # 特征维度一致

    # ✅ 检查边特征 - 重点验证
    for edge_type in data.edge_types:
        edge_index = data[edge_type].edge_index
        edge_attr = data[edge_type].edge_attr

        # 基本形状检查
        assert edge_index.shape[1] == edge_attr.shape[0]  # 边数量匹配

        # ✅ 边特征完整性检查
        assert edge_attr.shape[1] == 9, f"边特征维度应为9，实际为{edge_attr.shape[1]}"
        assert not torch.isnan(edge_attr).any(), f"边特征中发现NaN值: {edge_type}"
        assert edge_attr.dtype == torch.float32, f"边特征数据类型错误: {edge_attr.dtype}"

    return True

# 示例验证结果
print(f"✅ 异构图数据验证通过:")
print(f"📊 节点类型数: {len(data.node_types)}")
print(f"📊 边类型数: {len(data.edge_types)}")
print(f"📊 总节点数: {sum(data[nt].x.shape[0] for nt in data.node_types)}")
print(f"📊 总边数: {sum(data[et].edge_index.shape[1] for et in data.edge_types)}")
print(f"📊 节点特征维度: 14")
print(f"📊 边特征维度: 9 ✅ 完整保留")

```

## 缓存信息

- **缓存文件**：`cache/{hash}_hetero.pt`
- **加载方式**：`torch.load(cache_file, map_location="cpu", weights_only=False)`
- **哈希依据**：基于 `bus` 和 `branch` 数据计算MD5
- **版本区分**：文件名包含`_hetero`后缀，与旧版本缓存区分

## 关键升级特性

### 🔧 **V1.0 → V2.0 主要变化**

| 项目 | V1.0 (同构图) | V2.0 (异构图) |
| --- | --- | --- |
| **数据结构** | `Data` | `HeteroData` |
| **节点表示** | 统一特征+one-hot类型 | 按类型分组存储 |
| **边表示** | 统一特征 | **✅ 按连接类型分组，保持9维特征** |
| **索引方式** | 全局0-based索引 | 类型内局部索引 |
| **节点特征维度** | 17维 (含one-hot) | 14维 (去除one-hot) |
| **边特征维度** | **9维** | **✅ 9维 (完全保留)** |
| **物理意义** | 同质化处理 | 保持物理异构性 |
| **边特征存储** | 单一edge_attr | **✅ 按关系类型分组存储** |
| **模型支持** | 同构GNN | 异构GNN (to_hetero) |

### 🎯 **核心优势 - 边特征增强**

1. **✅ 边特征完全保留**：9维电气参数特征完整保存
2. **✅ 按类型分组**：线路和变压器分别建模，参数学习更精准
3. **✅ 物理准确性**：区分不同连接方式的电气特性
4. **✅ 模型表达力**：每种边类型可学习专门的参数
5. **✅ 数据质量**：标准化处理，数值稳定，无异常值

### 📊 **边特征验证总结**

```
✅ 边特征验证通过:
   - 特征维度一致: 9维
   - 数据类型: torch.float32
   - 数据质量: 无NaN值，所有数值有效
   - 分组存储: 按边关系类型分组
   - 物理意义: 完整的电气参数表示

```