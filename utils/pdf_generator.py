"""
PDF Report Generator for SmartTrader Pro
Generates a professional weekly performance summary.
"""
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from datetime import datetime
from pathlib import Path

class PDFReportGenerator:
    def __init__(self, output_dir: str = "output/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        self.styles.add(ParagraphStyle(
            name='MetricValue',
            parent=self.styles['Normal'],
            fontSize=14,
            textColor=colors.HexColor("#007A5E"),
            spaceAfter=10
        ))
        self.styles.add(ParagraphStyle(
            name='Header1',
            parent=self.styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor("#00FFA3"),
            alignment=1,
            spaceAfter=20
        ))

    def generate_weekly_report(self, metrics: dict, trades: list) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"Weekly_Report_{timestamp}.pdf"
        filepath = self.output_dir / filename
        
        doc = SimpleDocTemplate(str(filepath), pagesize=A4)
        elements = []

        # Title
        elements.append(Paragraph("SmartTrader Pro - Weekly Performance", self.styles['Header1']))
        elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", self.styles['Normal']))
        elements.append(Spacer(1, 20))

        # Key Metrics Table
        elements.append(Paragraph("Key Performance Indicators", self.styles['Heading2']))
        metric_data = [
            ["Metric", "Value"],
            ["Total Return", metrics.get('total_return', '0.0%')],
            ["Win Rate", metrics.get('win_rate', '0.0%')],
            ["Sharpe Ratio", metrics.get('sharpe_ratio', '0.0')],
            ["Max Drawdown", metrics.get('max_drawdown', '0.0%')],
            ["Profit Factor", metrics.get('profit_factor', '0.0')],
            ["Total Trades", str(metrics.get('total_trades', '0'))],
            ["Closed Trades", str(metrics.get('closed_trades', '0'))]
        ]
        
        t = Table(metric_data, colWidths=[200, 100])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.hexColor("#1A1C24")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        elements.append(t)
        elements.append(Spacer(1, 30))

        # Recent Trades Table
        elements.append(Paragraph("Recent Trade Activity (Closed)", self.styles['Heading2']))
        trade_data = [["Ticker", "Signal", "Entry", "Exit", "P&L %"]]
        
        closed_trades = [t for t in trades if t['status'] == 'CLOSED']
        for trade in closed_trades[-10:]: # Last 10 trades
            trade_data.append([
                trade['ticker'],
                trade['signal'],
                f"{trade['entry_price']:.2f}",
                f"{trade['exit_price']:.2f}",
                f"{trade['pnl_pct']:.2%}"
            ])

        if len(trade_data) > 1:
            t2 = Table(trade_data, colWidths=[100, 80, 80, 80, 100])
            t2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.hexColor("#1A1C24")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
            ]))
            elements.append(t2)
        else:
            elements.append(Paragraph("No closed trades this period.", self.styles['Normal']))

        doc.build(elements)
        return str(filepath)
