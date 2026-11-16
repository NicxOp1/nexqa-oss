from html import escape
from nexqa.storage.config import Config
from nexqa.models.scenario_models import EvaluationResult
from typing import List
from datetime import datetime

class HtmlReportGenerator:
    """Generates HTML reports using Jinja2 templates"""
    
    def generate(self, results: List[EvaluationResult], version: str):
        report_data = {
            "version": version,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "results": [r.model_dump() for r in results],
            "average_score": sum(r.overall_score for r in results) / len(results) if results else 0
        }
        
        html_content = self._render_template(report_data)
        
        filename = f"report_{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        Config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = Config.REPORTS_DIR / filename
        output_path.write_text(html_content, encoding="utf-8")
        return output_path

    def _render_template(self, data: dict) -> str:
        # Minimal embedded template
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>NEXQA Report {escape(str(data['version']))}</title>
            <style>
                body {{ font-family: sans-serif; background: #1e1e1e; color: #fff; padding: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #444; padding: 10px; text-align: left; }}
                th {{ background: #333; }}
                .score {{ font-size: 2em; font-weight: bold; }}
                .pass {{ color: #4caf50; }}
                .fail {{ color: #f44336; }}
            </style>
        </head>
        <body>
            <h1>NEXQA Report - {escape(str(data['version']))}</h1>
            <p>Date: {data['date']}</p>
            <p class="score">Average Score: {data['average_score']:.2f}</p>
            
            <table>
                <thead>
                    <tr>
                        <th>Scenario</th>
                        <th>Deterministic</th>
                        <th>Semantic</th>
                        <th>Overall</th>
                        <th>Issues</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join([self._row(r) for r in data['results']])}
                </tbody>
            </table>
        </body>
        </html>
        """

    def _row(self, result: dict) -> str:
        status_class = "pass" if not result['is_critical_fail'] else "fail"
        # Issue text comes from transcripts and the LLM judge: escape it.
        issues = escape(", ".join(i["description"] for i in result["semantic_issues"]))
        return f"""
        <tr class="{status_class}">
            <td>{escape(str(result['scenario_id']))}</td>
            <td>{'PASS' if result['deterministic_result']['passed'] else 'FAIL'}</td>
            <td>{result['semantic_score']:.2f}</td>
            <td>{result['overall_score']:.2f}</td>
            <td>{issues}</td>
        </tr>
        """

html_reporter = HtmlReportGenerator()
