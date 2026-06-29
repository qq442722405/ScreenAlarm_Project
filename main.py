# 在 MainWindow 类中添加以下方法
def keyPressEvent(self, event):
    """全局键盘事件：Ctrl+↑/↓ 移动当前行"""
    if event.modifiers() == Qt.ControlModifier:
        if event.key() == Qt.Key_Up:
            self._move_row_up()
            event.accept()
        elif event.key() == Qt.Key_Down:
            self._move_row_down()
            event.accept()
    super().keyPressEvent(event)

def _move_row_up(self):
    row = self.table.currentRow()
    if row > 0:
        self._swap_rows(row, row - 1)
        self.table.selectRow(row - 1)

def _move_row_down(self):
    row = self.table.currentRow()
    if row < self.table.rowCount() - 1:
        self._swap_rows(row, row + 1)
        self.table.selectRow(row + 1)

def _swap_rows(self, row1, row2):
    """交换两行数据，保持内容一致性"""
    # 交换所有列的数据（包括 widget）
    for col in range(self.table.columnCount()):
        item1 = self.table.takeItem(row1, col)
        item2 = self.table.takeItem(row2, col)
        self.table.setItem(row1, col, item2)
        self.table.setItem(row2, col, item1)
        # 交换 cellWidget（如复选框、滑块等）
        w1 = self.table.cellWidget(row1, col)
        w2 = self.table.cellWidget(row2, col)
        self.table.setCellWidget(row1, col, w2)
        self.table.setCellWidget(row2, col, w1)
    # 更新内部映射（启用、静音、灵敏度）
    self.row_enabled[row1], self.row_enabled[row2] = self.row_enabled.get(row2, True), self.row_enabled.get(row1, True)
    self.row_muted[row1], self.row_muted[row2] = self.row_muted.get(row2, False), self.row_muted.get(row1, False)
    self.row_sensitivity[row1], self.row_sensitivity[row2] = self.row_sensitivity.get(row2, 5), self.row_sensitivity.get(row1, 5)
    # 清空历史趋势（行号变化无法对应）
    self.value_history.clear()
    self.status_label.setText("状态: 行顺序已改变，历史趋势数据已重置")
    # 如果监控运行，重启以同步
    if self.monitoring:
        self.stop_monitor()
        self.start_monitor()
