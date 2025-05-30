import backtrader as bt
from loguru import logger

class SyncLongHedge:
    def __init__(self, strategy):
        self.strategy = strategy
        self.enabled = False
        self.hedge_position = None
        self.hedge_entry_price = None
        self.hedge_order = None
        self.hedge_contract_code = None
        self.hedge_entry_date = None  # 添加入场日期记录
        
    def enable(self):
        """启用同步做多对冲功能"""
        self.enabled = True
        logger.info("启用同步做多对冲功能")
        
    def disable(self):
        """禁用同步做多对冲功能"""
        self.enabled = False
        logger.info("禁用同步做多对冲功能")
        
    def on_golden_cross(self):
        """在ETF金叉时同步开多期货"""
        if not self.enabled:
            return
            
        if self.hedge_position is not None or self.hedge_order is not None:
            logger.info("已有对冲仓位或对冲订单，不再开仓")
            return
            
        try:
            # 计算ATR止盈止损价格
            current_atr = self.strategy.atr[0]
            stop_loss = self.strategy.data1.close[0] - (current_atr * self.strategy.p.atr_loss_multiplier)
            take_profit = self.strategy.data1.close[0] + (current_atr * self.strategy.p.atr_profit_multiplier)
            
            # 开多豆粕期货
            hedge_size = self.strategy.p.hedge_contract_size
            self.hedge_order = self.strategy.buy(data=self.strategy.data1, size=hedge_size)
            
            if self.hedge_order:
                # 记录入场价格和合约代码
                self.hedge_entry_price = self.strategy.data1.close[0]
                # 确保获取正确的合约代码
                current_date = self.strategy.data1.datetime.datetime(0)
                if hasattr(self.strategy.data1, 'contract_mapping') and current_date in self.strategy.data1.contract_mapping:
                    self.hedge_contract_code = self.strategy.data1.contract_mapping[current_date]
                else:
                    # 如果无法获取映射，使用数据名称
                    self.hedge_contract_code = self.strategy.data1._name
                self.hedge_entry_date = self.strategy.data.datetime.date(0)  # 记录入场日期
                
                # 计算保证金
                margin = self.hedge_entry_price * hedge_size * self.strategy.p.future_contract_multiplier * 0.10
                
                # 从期货账户扣除保证金
                pre_cash = self.strategy.future_cash
                self.strategy.future_cash -= margin
                
                logger.info(f"开仓扣除保证金 - 之前: {pre_cash:.2f}, 扣除: {margin:.2f}, 之后: {self.strategy.future_cash:.2f}")
                
                # 记录交易信息
                self.hedge_order.info = {
                    'reason': f"ETF金叉同步开多 - 快线: {self.strategy.fast_ma[0]:.2f}, 慢线: {self.strategy.slow_ma[0]:.2f}",
                    'margin': margin,
                    'future_cash': self.strategy.future_cash,
                    'execution_date': self.hedge_entry_date,
                    'total_value': self.strategy.future_cash,
                    'position_value': abs(margin),
                    'position_ratio': margin / self.strategy.future_cash if self.strategy.future_cash > 0 else 0,
                    'etf_code': self.hedge_contract_code,
                    'pnl': 0,
                    'return': 0,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'avg_cost': self.hedge_entry_price
                }
                
                logger.info(f"ETF金叉同步开多 - 合约: {self.hedge_contract_code}, 价格: {self.hedge_entry_price:.2f}, 数量: {hedge_size}手, "
                          f"止损价: {stop_loss:.2f}, 止盈价: {take_profit:.2f}")
                
        except Exception as e:
            logger.error(f"ETF金叉同步开多失败: {str(e)}")
            
    def on_etf_close(self):
        """在ETF平仓时同步平多仓"""
        if not self.enabled or not self.hedge_position:
            return
            
        if self.hedge_order is None:  # 确保没有未完成订单
            self.hedge_order = self.strategy.close(data=self.strategy.data1)
            logger.info("ETF平仓，同步平多仓")
            
    def check_exit(self):
        """检查是否需要平仓"""
        if not self.enabled or not self.hedge_position or self.hedge_order is not None:
            return
            
        current_price = self.strategy.data1.close[0]
        current_atr = self.strategy.atr[0]
        
        # 计算ATR止盈止损价格
        stop_loss = self.hedge_entry_price - (current_atr * self.strategy.p.atr_loss_multiplier)
        take_profit = self.hedge_entry_price + (current_atr * self.strategy.p.atr_profit_multiplier)
        
        # 获取当前日期
        current_date = self.strategy.data.datetime.date(0)
        
        # 检查是否触发止盈止损
        if current_price <= stop_loss or current_price >= take_profit:
            contract_code = self.hedge_contract_code
            self.hedge_order = self.strategy.close(data=self.strategy.data1)
            reason = "触发止盈" if current_price >= take_profit else "触发止损"
            logger.info(f"同步做多对冲{reason} - 日期: {current_date}, 合约: {contract_code}, 当前价格: {current_price:.2f}, {reason}价: {take_profit if current_price >= take_profit else stop_loss:.2f}")

    def on_order_completed(self, order):
        """处理订单完成事件"""
        if not self.enabled:
            return
            
        if order.status in [order.Completed]:
            if order.issell():  # 卖出豆粕期货（平多）
                # 确保有对应的入场价格
                if self.hedge_entry_price is None or self.hedge_contract_code is None:
                    logger.error("平仓时找不到入场价格或合约代码，跳过处理")
                    return
                
                # 记录平仓前的合约信息，用于日志
                entry_price = self.hedge_entry_price
                contract_code = self.hedge_contract_code
                entry_date = self.hedge_entry_date
                
                # 记录交易日期和价格
                trade_date = self.strategy.data.datetime.date(0)
                trade_price = order.executed.price
                
                # 先重置持仓相关变量，防止重复平仓
                self.hedge_position = None
                self.hedge_order = None
                self.hedge_entry_price = None
                self.hedge_contract_code = None
                self.hedge_entry_date = None
                self.hedge_target_profit = None
                
                # 计算对冲盈亏
                hedge_profit = (trade_price - entry_price) * self.strategy.p.hedge_contract_size * self.strategy.p.future_contract_multiplier
                
                # 减去开平仓手续费
                total_fee = self.strategy.p.hedge_fee * self.strategy.p.hedge_contract_size * 2
                net_profit = hedge_profit - total_fee
                
                # 归还保证金并添加盈亏到期货账户
                margin_returned = entry_price * self.strategy.p.hedge_contract_size * self.strategy.p.future_contract_multiplier * 0.10
                
                # 记录更新前的资金
                pre_cash = self.strategy.future_cash
                
                # 更新期货账户资金
                self.strategy.future_cash += (margin_returned + net_profit)
                
                # 记录资金变动
                logger.info(f"平仓资金变动 - 之前: {pre_cash:.2f}, 返还保证金: {margin_returned:.2f}, 盈亏: {net_profit:.2f}, 之后: {self.strategy.future_cash:.2f}")
                
                # 更新期货账户最高净值
                self.strategy.future_highest_value = max(self.strategy.future_highest_value, self.strategy.future_cash)
                
                # 计算期货账户回撤
                future_drawdown = (self.strategy.future_highest_value - self.strategy.future_cash) / self.strategy.future_highest_value if self.strategy.future_highest_value > 0 else 0
                
                # 计算收益率
                return_pct = (hedge_profit / (entry_price * self.strategy.p.hedge_contract_size * self.strategy.p.future_contract_multiplier)) * 100
                
                # 更新订单信息
                order.info.update({
                    'pnl': hedge_profit,
                    'return': return_pct,
                    'total_value': self.strategy.future_cash,
                    'position_value': 0,  # 平仓后持仓价值为0
                    'avg_cost': entry_price,
                    'etf_code': contract_code,  # 确保使用原始合约代码
                    'execution_date': trade_date,  # 确保使用当前交易日期
                    'reason': f"同步做多对冲平仓 - 合约: {contract_code}, 入场日期: {entry_date}, 入场价: {entry_price:.2f}, 平仓价: {trade_price:.2f}, 收益率: {return_pct:.2f}%"
                })
                
                logger.info(f"同步做多对冲平仓 - 日期: {trade_date}, 合约: {contract_code}, 价格: {trade_price:.2f}, 盈利: {hedge_profit:.2f}, "
                          f"手续费: {total_fee:.2f}, 净盈利: {net_profit:.2f}, "
                          f"期货账户余额: {self.strategy.future_cash:.2f}, 回撤: {future_drawdown:.2%}, "
                          f"收益率: {return_pct:.2f}%")
                
            else:  # 买入豆粕期货（开多）
                # 记录对冲持仓
                self.hedge_position = order
                
                # 更新订单信息
                order.info.update({
                    'total_value': self.strategy.future_cash,
                    'position_value': abs(order.info['margin']),
                    'avg_cost': order.executed.price,
                    'etf_code': self.hedge_contract_code  # 确保合约代码正确
                })
                
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.hedge_order = None
            logger.warning(f'同步做多对冲订单失败 - 状态: {order.getstatusname()}')
            
    def on_strategy_stop(self):
        """策略结束时平掉所有期货仓位"""
        if not self.enabled or not self.hedge_position:
            return
            
        if self.hedge_order is None:  # 确保没有未完成订单
            # 获取当前持仓的合约代码
            current_contract = self.hedge_contract_code
            if not current_contract:
                logger.error("策略结束时找不到期货合约代码，无法平仓")
                return
                
            # 获取当前日期
            current_date = self.strategy.data.datetime.date(0)
            
            self.hedge_order = self.strategy.close(data=self.strategy.data1)
            logger.info(f"策略结束，平掉期货仓位 - 日期: {current_date}, 合约: {current_contract}, 入场日期: {self.hedge_entry_date}, 入场价: {self.hedge_entry_price:.2f}")
            
            # 更新订单信息
            if self.hedge_order:
                self.hedge_order.info.update({
                    'etf_code': current_contract,  # 确保使用正确的合约代码
                    'execution_date': current_date,  # 使用当前日期
                    'reason': f"策略结束平仓 - 日期: {current_date}, 合约: {current_contract}, 入场日期: {self.hedge_entry_date}, 入场价: {self.hedge_entry_price:.2f}"
                }) 