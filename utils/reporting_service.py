import logging
from typing import List, Dict
from pathlib import Path

from utils.pdf_generator import PDFReportGenerator
from utils.performance_report import PerformanceReport

logger = logging.getLogger(__name__)

class ReportingService:
    """Handles generating performance reports, separating reporting logic from trading logic."""
    
    def __init__(self):
        self.pdf_gen = PDFReportGenerator()

    def generate_weekly_report(self, db_connection) -> str:
        """Fetch trades from DB and generate a weekly PDF report."""
        logger.info("ReportingService: Generating weekly performance report PDF...")
        try:
            cursor = db_connection.execute("SELECT * FROM paper_trades")
            cols = [d[0] for d in cursor.description]
            trades = [dict(zip(cols, row)) for row in cursor.fetchall()]
            if not trades:
                logger.info("ReportingService: No trades found to report.")
                return ""
                
            metrics = PerformanceReport.generate_metrics(trades)
            if not metrics or "status" in metrics:
                metrics = {"total_trades": len(trades), "closed_trades": 0}
                
            report_path = self.pdf_gen.generate_weekly_report(metrics, trades)
            logger.info(f"ReportingService: Weekly report saved to {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"ReportingService: Error generating PDF report: {e}")
            return ""
