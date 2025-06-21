# 训练过程监控指南

本指南介绍如何观测和监控电力网络分区强化学习训练过程。

## 🎯 监控功能概览

### 1. 增强的训练日志记录
- **实时指标记录**: 奖励、回合长度、成功率、负载CV等
- **TensorBoard集成**: 自动记录训练曲线和指标
- **控制台输出**: 定期显示训练进度
- **中间检查点**: 自动保存训练统计信息

### 2. 实时监控工具
- **实时图表**: 6个子图显示关键训练指标
- **自动更新**: 定期刷新显示最新数据
- **移动平均**: 平滑显示训练趋势

### 3. 进度检查工具
- **快速状态查看**: 一键查看当前训练状态
- **历史结果分析**: 查看完整训练历史
- **持续监控模式**: 自动定期检查进度

## 🚀 使用方法

### 启动训练（带监控）

```bash
# 标准训练（已启用监控功能）
python train_unified.py --mode standard

# 启用TensorBoard和保存结果
python train_unified.py --mode standard --save-results

# 自定义监控间隔
python train_unified.py --mode standard --config config_unified.yaml
```

### 实时监控训练过程

在训练开始后，打开新的终端窗口：

```bash
# 启动实时监控（图形界面）
python monitor_training.py

# 自定义监控参数
python monitor_training.py --log-dir logs --checkpoint-dir checkpoints --interval 5
```

### 检查训练进度

```bash
# 快速检查当前状态
python check_training_progress.py

# 持续监控模式
python check_training_progress.py --watch --interval 10

# 自定义目录
python check_training_progress.py --checkpoint-dir checkpoints --results-dir experiments
```

### 使用TensorBoard

```bash
# 启动TensorBoard
tensorboard --logdir=logs

# 在浏览器中访问
# http://localhost:6006
```

## 📊 监控指标说明

### 核心训练指标
- **Episode Reward**: 每回合获得的总奖励
- **Episode Length**: 每回合的步数
- **Success Rate**: 成功完成分区的比例
- **Load CV**: 负载变异系数（越小越好）

### 训练损失指标
- **Actor Loss**: 策略网络损失
- **Critic Loss**: 价值网络损失
- **Entropy**: 策略熵（探索程度）

### 性能指标
- **Best Reward**: 历史最佳奖励
- **Moving Average**: 奖励移动平均
- **Training Time**: 累计训练时间

## 🔧 配置选项

### 日志配置 (config_unified.yaml)

```yaml
logging:
  use_tensorboard: true          # 启用TensorBoard
  log_dir: logs                  # 日志目录
  checkpoint_dir: checkpoints    # 检查点目录
  console_log_interval: 10       # 控制台日志间隔
  metrics_save_interval: 50      # 指标保存间隔
  tensorboard_log_interval: 1    # TensorBoard日志间隔
```

### 可视化配置

```yaml
visualization:
  enabled: true                  # 启用可视化
  save_figures: true            # 保存图片
  figures_dir: figures          # 图片目录
  interactive: true             # 交互式图表
```

## 📁 输出文件结构

```
project/
├── logs/                      # TensorBoard日志
│   └── training_20231221_143022/
├── checkpoints/               # 训练检查点
│   ├── training_stats_episode_50.json
│   ├── training_stats_episode_100.json
│   └── ...
├── experiments/               # 最终结果
│   ├── standard_results_20231221_143500.json
│   └── standard_report_20231221_143500.md
└── figures/                   # 可视化图片
    ├── training_curves.png
    └── partition_result.png
```

## 🎨 监控界面说明

### 实时监控窗口 (monitor_training.py)
- **左上**: 训练奖励曲线（含移动平均）
- **中上**: 回合长度变化
- **右上**: 成功率趋势
- **左下**: 负载变异系数
- **中下**: Actor损失
- **右下**: Critic损失

### TensorBoard界面
- **SCALARS**: 所有数值指标的时间序列
- **GRAPHS**: 网络结构图
- **DISTRIBUTIONS**: 参数分布

## 🔍 故障排除

### 常见问题

1. **TensorBoard无法启动**
   ```bash
   pip install tensorboard
   ```

2. **实时监控无数据**
   - 确保训练已开始
   - 检查检查点目录是否存在
   - 确认文件权限

3. **图表显示异常**
   ```bash
   pip install matplotlib numpy
   ```

### 性能优化

1. **减少日志频率**: 增大 `console_log_interval`
2. **关闭TensorBoard**: 设置 `use_tensorboard: false`
3. **减少检查点**: 增大 `metrics_save_interval`

## 📈 最佳实践

### 训练监控建议
1. **开始训练前**: 确认监控配置正确
2. **训练期间**: 定期查看实时监控
3. **训练完成后**: 分析TensorBoard日志
4. **长期训练**: 使用持续监控模式

### 指标解读
- **奖励上升**: 训练进展良好
- **奖励震荡**: 可能需要调整学习率
- **成功率低**: 检查环境设置和奖励函数
- **损失不收敛**: 考虑调整网络结构

## 🎯 高级功能

### 自定义监控指标
可以在 `TrainingLogger` 中添加新的指标记录。

### 多实验对比
使用不同配置运行多次实验，然后对比结果。

### 自动化监控
结合脚本实现自动化训练和监控流程。

---

## 📞 技术支持

如果遇到问题，请检查：
1. 依赖包是否正确安装
2. 配置文件格式是否正确
3. 文件权限是否足够
4. 磁盘空间是否充足
