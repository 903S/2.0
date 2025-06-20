import torch
import numpy as np
from typing import Dict, Tuple, List, Optional, Union, Any
from torch_geometric.data import HeteroData
import copy

from .state import StateManager
from .action_space import ActionSpace, ActionMask
from .reward import RewardFunction
from .utils import MetisInitializer, PartitionEvaluator


class PowerGridPartitioningEnv:
    """
    电力网络分割MDP环境
    """

    def __init__(self,
                 hetero_data: HeteroData,
                 node_embeddings: Dict[str, torch.Tensor],
                 num_partitions: int,
                 reward_weights: Dict[str, float] = None,
                 max_steps: int = 200,
                 device: torch.device = None,
                 attention_weights: Dict[str, torch.Tensor] = None):
        """
        初始化电力网络分割环境

        参数:
            hetero_data: 来自数据处理的异构图数据
            node_embeddings: GAT编码器预计算的节点嵌入
            num_partitions: 目标分区数量（K）
            reward_weights: 奖励组件权重
            max_steps: 每个回合的最大步数
            device: 用于计算的Torch设备
            attention_weights: GAT编码器注意力权重，用于增强嵌入
        """
        self.device = device or torch.device('cpu')
        self.hetero_data = hetero_data.to(self.device)
        self.num_partitions = num_partitions
        self.max_steps = max_steps

        # 生成增强的节点嵌入（如果提供了注意力权重）
        enhanced_embeddings = self._generate_enhanced_embeddings(
            node_embeddings, attention_weights
        ) if attention_weights else node_embeddings

        # 初始化核心组件
        self.state_manager = StateManager(hetero_data, enhanced_embeddings, device)
        self.action_space = ActionSpace(hetero_data, num_partitions, device)
        self.reward_function = RewardFunction(hetero_data, reward_weights, device)
        self.metis_initializer = MetisInitializer(hetero_data, device)
        self.evaluator = PartitionEvaluator(hetero_data, device)
        
        # 环境状态
        self.current_step = 0
        self.episode_history = []
        self.is_terminated = False
        self.is_truncated = False
        
        # 缓存频繁使用的数据
        self._setup_cached_data()
        
    def _setup_cached_data(self):
        """设置频繁访问的缓存数据"""
        # 所有类型节点的总数
        self.total_nodes = sum(x.shape[0] for x in self.hetero_data.x_dict.values())
        
        # 全局节点映射（本地索引到全局索引）
        self.global_node_mapping = self.state_manager.get_global_node_mapping()
        
        # 用于奖励计算的边信息
        self.edge_info = self._extract_edge_info()
        
    def _extract_edge_info(self) -> Dict[str, torch.Tensor]:
        """提取奖励计算所需的边信息"""
        edge_info = {}
        
        # 收集所有边及其属性
        all_edges = []
        all_edge_attrs = []
        
        for edge_type, edge_index in self.hetero_data.edge_index_dict.items():
            edge_attr = self.hetero_data.edge_attr_dict[edge_type]
            
            # 将本地索引转换为全局索引
            src_type, _, dst_type = edge_type
            src_global = self.state_manager.local_to_global(edge_index[0], src_type)
            dst_global = self.state_manager.local_to_global(edge_index[1], dst_type)
            
            global_edges = torch.stack([src_global, dst_global], dim=0)
            all_edges.append(global_edges)
            all_edge_attrs.append(edge_attr)
        
        edge_info['edge_index'] = torch.cat(all_edges, dim=1)
        edge_info['edge_attr'] = torch.cat(all_edge_attrs, dim=0)
        
        return edge_info

    def _generate_enhanced_embeddings(self,
                                    node_embeddings: Dict[str, torch.Tensor],
                                    attention_weights: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        生成增强的静态节点特征嵌入 H'

        将边级注意力权重聚合为节点特征，然后与原始嵌入连接

        参数:
            node_embeddings: 原始节点嵌入 H
            attention_weights: GAT编码器的边级注意力权重

        返回:
            enhanced_embeddings: 增强的节点嵌入 H' = concat(H, H_attn)
        """
        print("🔧 生成增强的静态节点特征嵌入 H'...")

        # 步骤1：计算每个节点的聚合注意力分数
        node_attention_scores = self._aggregate_attention_to_nodes(attention_weights)

        # 步骤2：将注意力分数与原始嵌入连接
        enhanced_embeddings = {}

        for node_type, embeddings in node_embeddings.items():
            # 获取该节点类型的注意力分数
            if node_type in node_attention_scores:
                attention_features = node_attention_scores[node_type]
                # 连接原始嵌入和注意力特征: H' = concat(H, H_attn)
                enhanced_emb = torch.cat([embeddings, attention_features], dim=1)
                enhanced_embeddings[node_type] = enhanced_emb

                print(f"  ✅ {node_type}: {embeddings.shape} + {attention_features.shape} → {enhanced_emb.shape}")
            else:
                # 如果没有注意力权重，使用原始嵌入
                enhanced_embeddings[node_type] = embeddings
                print(f"  ⚠️ {node_type}: 无注意力权重，使用原始嵌入 {embeddings.shape}")

        print(f"✅ 增强嵌入生成完成")
        return enhanced_embeddings

    def _aggregate_attention_to_nodes(self,
                                    attention_weights: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        将边级注意力权重聚合为节点级特征

        对每个节点 i，计算其聚合注意力分数：
        h_attn(i) = (1/|N(i)|) * Σ_{j ∈ N(i)} α_{j→i}

        参数:
            attention_weights: 边级注意力权重字典

        返回:
            node_attention_scores: 每个节点类型的注意力分数 [num_nodes, 1]
        """
        print("  🔍 聚合边级注意力权重到节点级特征...")

        # 初始化节点注意力分数累积器
        node_attention_accumulator = {}
        node_degree_counter = {}

        # 初始化所有节点类型的累积器
        for node_type in self.hetero_data.x_dict.keys():
            num_nodes = self.hetero_data.x_dict[node_type].shape[0]
            node_attention_accumulator[node_type] = torch.zeros(num_nodes, device=self.device)
            node_degree_counter[node_type] = torch.zeros(num_nodes, device=self.device)

        # 处理每种边类型
        for edge_type, edge_index in self.hetero_data.edge_index_dict.items():
            src_type, relation, dst_type = edge_type
            
            # 使用改进的键匹配，找不到时返回None
            attn_weights = self._get_attention_weights_for_edge_type(
                edge_type, attention_weights, edge_type_to_key_mapping
            )
            
            # 如果找不到权重，则跳过此边类型
            if attn_weights is None:
                continue
            
            # 处理维度和多头注意力（维度不匹配时返回None）
            processed_weights = self._process_attention_weights(
                attn_weights, edge_index, edge_type
            )
            
            # 如果权重处理失败（如维度不匹配），则跳过此边类型
            if processed_weights is None:
                continue
            
            # 高效的节点聚合
            dst_nodes = edge_index[1]
            node_attention_accumulator[dst_type].index_add_(0, dst_nodes, processed_weights)
            node_degree_counter[dst_type].index_add_(0, dst_nodes, torch.ones_like(processed_weights))

            print(f"    �� {edge_type}: {len(processed_weights)} 条边的注意力权重已聚合")

        # 计算平均注意力分数（避免除零）
        node_attention_scores = {}
        for node_type in node_attention_accumulator.keys():
            degrees = node_degree_counter[node_type]
            # 避免除零：度为0的节点注意力分数设为0
            avg_attention = torch.where(
                degrees > 0,
                node_attention_accumulator[node_type] / degrees,
                torch.zeros_like(node_attention_accumulator[node_type])
            )

            # 转换为列向量 [num_nodes, 1]
            node_attention_scores[node_type] = avg_attention.unsqueeze(1)

            print(f"    ✅ {node_type}: 平均注意力分数计算完成 {node_attention_scores[node_type].shape}")

        return node_attention_scores

    def _get_attention_weights_for_edge_type(self,
                                            edge_type: tuple,
                                            attention_weights: Dict[str, torch.Tensor],
                                            edge_type_to_key_mapping: Dict[str, str]) -> Optional[torch.Tensor]:
        """
        获取特定边类型的注意力权重

        参数:
            edge_type: 边类型 (src_type, relation, dst_type)
            attention_weights: 边级注意力权重字典
            edge_type_to_key_mapping: 边类型到注意力权重键的映射

        返回:
            找到的注意力权重，如果找不到则返回None
        """
        # 构建边类型到注意力权重键的映射
        edge_type_key = f"{edge_type[0]}__{edge_type[1]}__{edge_type[2]}"
        edge_type_to_key_mapping[edge_type_key] = edge_type_key

        # 尝试多种键格式来查找注意力权重
        found_weights = None
        used_key = None

        # 1. 尝试标准格式
        if edge_type_key in attention_weights:
            found_weights = attention_weights[edge_type_key]
            used_key = edge_type_key
        else:
            # 2. 尝试查找包含相关信息的键
            for key, weights in attention_weights.items():
                if (edge_type[0] in key and edge_type[2] in key and edge_type[1] in key) or \
                   ("unknown_edge_type" in key):
                    found_weights = weights
                    used_key = key
                    break

        if found_weights is None:
            print(f"    ⚠️ 未找到边类型 {edge_type_key} 的注意力权重")
            print(f"       可用的注意力权重键: {list(attention_weights.keys())}")
            return None

        attn_weights = found_weights.to(self.device)
        print(f"    🔍 边类型 {edge_type} 使用注意力权重键: {used_key}")
        return attn_weights

    def _process_attention_weights(self, 
                                 attn_weights: torch.Tensor,
                                 edge_index: torch.Tensor,
                                 edge_type: tuple) -> Optional[torch.Tensor]:
        """
        处理注意力权重的维度和多头注意力。
        如果维度不匹配，则返回 None，表示忽略此权重。
        """
        num_edges = edge_index.shape[1]
        
        # 处理多头注意力
        if attn_weights.dim() > 1:
            if attn_weights.shape[-1] > 1:  # 多头注意力
                attn_weights = attn_weights.mean(dim=-1)
            else:
                attn_weights = attn_weights.squeeze(-1)
        
        # 维度验证
        if attn_weights.shape[0] != num_edges:
            print(
                f"    ⚠️ 注意力权重维度不匹配 - 边类型: {edge_type}, "
                f"权重数量: {attn_weights.shape[0]}, 边数量: {num_edges}."
            )
            print(f"    🔧 将忽略此边类型的注意力权重。")
            return None
        
        return attn_weights

    def reset(self, seed: Optional[int] = None) -> Tuple[Dict[str, torch.Tensor], Dict[str, Any]]:
        """
        将环境重置为初始状态
        
        参数:
            seed: 用于可重复性的随机种子
            
        返回:
            observation: 初始状态观察
            info: 附加信息
        """
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
            
        # 使用METIS初始化分区
        initial_partition = self.metis_initializer.initialize_partition(self.num_partitions)
        
        # 使用初始分区重置状态管理器
        self.state_manager.reset(initial_partition)
        
        # 重置环境状态
        self.current_step = 0
        self.episode_history = []
        self.is_terminated = False
        self.is_truncated = False
        
        # 获取初始观察
        observation = self.state_manager.get_observation()
        
        # 计算初始指标
        initial_metrics = self.evaluator.evaluate_partition(
            self.state_manager.current_partition
        )
        
        info = {
            'step': self.current_step,
            'metrics': initial_metrics,
            'partition': self.state_manager.current_partition.clone(),
            'boundary_nodes': self.state_manager.get_boundary_nodes(),
            'valid_actions': self.action_space.get_valid_actions(
                self.state_manager.current_partition,
                self.state_manager.get_boundary_nodes()
            )
        }
        
        return observation, info
        
    def step(self, action: Tuple[int, int]) -> Tuple[Dict[str, torch.Tensor], float, bool, bool, Dict[str, Any]]:
        """
        在环境中执行一步
        
        参数:
            action: (node_idx, target_partition)的元组
            
        返回:
            observation: 下一状态观察
            reward: 即时奖励
            terminated: 回合是否终止
            truncated: 回合是否被截断
            info: 附加信息
        """
        if self.is_terminated or self.is_truncated:
            raise RuntimeError("无法在已终止/截断的环境中执行步骤。请先调用reset()。")
            
        # 验证动作
        if not self.action_space.is_valid_action(
            action, 
            self.state_manager.current_partition,
            self.state_manager.get_boundary_nodes()
        ):
            # 无效动作 - 返回负奖励并终止
            observation = self.state_manager.get_observation()
            reward = -10.0  # 无效动作的大负奖励
            self.is_terminated = True
            
            info = {
                'step': self.current_step,
                'invalid_action': True,
                'action': action
            }
            
            return observation, reward, True, False, info
            
        # 执行动作
        node_idx, target_partition = action
        old_partition = self.state_manager.current_partition[node_idx].item()
        
        # 更新状态
        self.state_manager.update_partition(node_idx, target_partition)
        
        # 计算奖励
        reward = self.reward_function.compute_reward(
            self.state_manager.current_partition,
            self.state_manager.get_boundary_nodes(),
            action
        )
        
        # 更新步数计数器
        self.current_step += 1
        
        # 检查终止条件
        terminated, truncated = self._check_termination()
        
        # 获取下一观察
        observation = self.state_manager.get_observation()
        
        # 计算当前指标
        current_metrics = self.evaluator.evaluate_partition(
            self.state_manager.current_partition
        )
        
        # 记录历史步骤
        step_info = {
            'step': self.current_step,
            'action': action,
            'old_partition': old_partition,
            'new_partition': target_partition,
            'reward': reward,
            'metrics': current_metrics
        }
        self.episode_history.append(step_info)
        
        info = {
            'step': self.current_step,
            'metrics': current_metrics,
            'partition': self.state_manager.current_partition.clone(),
            'boundary_nodes': self.state_manager.get_boundary_nodes(),
            'valid_actions': self.action_space.get_valid_actions(
                self.state_manager.current_partition,
                self.state_manager.get_boundary_nodes()
            ) if not (terminated or truncated) else [],
            'episode_history': self.episode_history
        }
        
        self.is_terminated = terminated
        self.is_truncated = truncated
        
        return observation, reward, terminated, truncated, info
        
    def _check_termination(self) -> Tuple[bool, bool]:
        """
        检查回合是否应该终止或截断
        
        返回:
            terminated: 自然终止（收敛或无有效动作）
            truncated: 人工终止（达到最大步数）
        """
        # 检查截断（最大步数）
        if self.current_step >= self.max_steps:
            return False, True
            
        # 检查自然终止
        boundary_nodes = self.state_manager.get_boundary_nodes()
        valid_actions = self.action_space.get_valid_actions(
            self.state_manager.current_partition,
            boundary_nodes
        )
        
        # 没有剩余有效动作
        if len(valid_actions) == 0:
            return True, False
            
        # 收敛检查（如果启用）
        if self._check_convergence():
            return True, False
            
        return False, False
        
    def _check_convergence(self, window_size: int = 10, threshold: float = 0.01) -> bool:
        """
        基于最近奖励历史检查分区是否收敛
        
        参数:
            window_size: 要考虑的最近步数
            threshold: 收敛阈值
            
        返回:
            如果收敛返回True，否则返回False
        """
        if len(self.episode_history) < window_size:
            return False
            
        recent_rewards = [step['reward'] for step in self.episode_history[-window_size:]]
        reward_std = np.std(recent_rewards)
        
        return reward_std < threshold
        
    def render(self, mode: str = 'human') -> Optional[np.ndarray]:
        """
        渲染环境的当前状态
        
        参数:
            mode: 渲染模式（'human', 'rgb_array', 或 'ansi'）
            
        返回:
            渲染输出（取决于模式）
        """
        if mode == 'ansi':
            # 基于文本的渲染
            output = []
            output.append(f"步数: {self.current_step}/{self.max_steps}")
            output.append(f"分区数: {self.num_partitions}")
            output.append(f"总节点数: {self.total_nodes}")
            
            # 分区分布
            partition_counts = torch.bincount(
                self.state_manager.current_partition, 
                minlength=self.num_partitions + 1
            )[1:]  # 跳过分区0
            output.append(f"分区大小: {partition_counts.tolist()}")
            
            # 边界节点
            boundary_nodes = self.state_manager.get_boundary_nodes()
            output.append(f"边界节点: {len(boundary_nodes)}")
            
            return '\n'.join(output)
            
        elif mode == 'human':
            print(self.render('ansi'))
            return None
            
        else:
            raise NotImplementedError(f"渲染模式 '{mode}' 未实现")
            
    def close(self):
        """清理环境资源"""
        # 清理缓存数据
        if hasattr(self, 'edge_info'):
            del self.edge_info
        if hasattr(self, 'global_node_mapping'):
            del self.global_node_mapping
            
        # 清理组件引用
        self.state_manager = None
        self.action_space = None
        self.reward_function = None
        self.metis_initializer = None
        self.evaluator = None
        
    def get_action_mask(self) -> torch.Tensor:
        """
        获取当前状态的动作掩码
        
        返回:
            指示有效动作的布尔张量
        """
        return self.action_space.get_action_mask(
            self.state_manager.current_partition,
            self.state_manager.get_boundary_nodes()
        )
        
    def get_state_info(self) -> Dict[str, Any]:
        """
        获取当前状态的详细信息
        
        返回:
            包含状态信息的字典
        """
        return {
            'current_partition': self.state_manager.current_partition.clone(),
            'boundary_nodes': self.state_manager.get_boundary_nodes(),
            'step': self.current_step,
            'max_steps': self.max_steps,
            'num_partitions': self.num_partitions,
            'total_nodes': self.total_nodes,
            'is_terminated': self.is_terminated,
            'is_truncated': self.is_truncated
        }

    def clear_cache(self):
        """清理缓存数据"""
        # 清理缓存数据
        if hasattr(self, 'edge_info'):
            del self.edge_info
        if hasattr(self, 'global_node_mapping'):
            del self.global_node_mapping
            
        # 清理组件引用
        self.state_manager = None
        self.action_space = None
        self.reward_function = None
        self.metis_initializer = None
        self.evaluator = None
