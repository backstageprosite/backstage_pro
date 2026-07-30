from django.test import TestCase
from django.conf import settings
import os
import re

# ==============================================================================
# POLÍTICA DE VERSÃO DO PDF.JS (v4.2.67)
# ==============================================================================
# - O PDF.js está fixado na versão 4.2.67 por compatibilidade validada com a arquitetura atual via módulos (ES Modules).
# - A versão corrige a vulnerabilidade de segurança da série 3.x e NÃO deve ser reduzida (downgrade).
# - Atualizações futuras devem manter o `pdf.mjs` (principal) e o `pdf.worker.mjs` (worker) rigorosamente na mesma versão.
# - A atualização deve ser revisada periodicamente contra falhas críticas.
# - O visualizador NÃO deve utilizar CDNs externas para evitar dependências não confiáveis e garantir suporte PWA offline para assets estáticos.
# - O parâmetro `isEvalSupported` deve obrigatoriamente permanecer `false` para prevenir execução arbitrária dentro da renderização do PDF.
# ==============================================================================

class PDFJSSecurityTestCase(TestCase):
    def setUp(self):
        self.template_path = os.path.join(settings.BASE_DIR, 'core', 'templates', 'core', 'file_viewer.html')
        self.pdfjs_dir = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', 'js', 'pdfjs')
        
    def test_pdfjs_version_and_files(self):
        """Confirma que as versoes 3.x nao existem e os modulos 4.x seguros estao no lugar."""
        old_pdf_js = os.path.join(self.pdfjs_dir, 'pdf.min.js')
        old_worker_js = os.path.join(self.pdfjs_dir, 'pdf.worker.min.js')
        self.assertFalse(os.path.exists(old_pdf_js), "Versão antiga do pdf.min.js ainda existe!")
        self.assertFalse(os.path.exists(old_worker_js), "Versão antiga do pdf.worker.min.js ainda existe!")
        
        new_pdf_mjs = os.path.join(self.pdfjs_dir, 'pdf.mjs')
        new_worker_mjs = os.path.join(self.pdfjs_dir, 'pdf.worker.mjs')
        self.assertTrue(os.path.exists(new_pdf_mjs), "Módulo pdf.mjs seguro não encontrado!")
        self.assertTrue(os.path.exists(new_worker_mjs), "Módulo pdf.worker.mjs seguro não encontrado!")

        # Check version inside the new files
        with open(new_pdf_mjs, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('4.2.67', content, "A versão do pdf.mjs não é a 4.2.67 esperada.")
            self.assertNotIn('3.11.', content, "A versão 3.x foi encontrada dentro do pdf.mjs!")

    def test_template_security_configurations(self):
        """Confirma que o template usa import de módulos, isEvalSupported false e não usa CDNs."""
        with open(self.template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertIn('type="module"', content, "O template não está carregando o PDF.js como um módulo ES.")
        self.assertIn('pdf.mjs', content, "O template não referencia o módulo pdf.mjs.")
        self.assertIn('pdf.worker.mjs', content, "O template não referencia o pdf.worker.mjs.")
        self.assertIn('isEvalSupported: false', content, "O template não desabilita a execução de scripts via isEvalSupported!")
        
        # Ensure no CDNs for PDF.js
        self.assertNotIn('cloudflare.com/ajax/libs/pdf.js', content, "O template contém referência a CDN externa para PDF.js!")
        self.assertNotIn('unpkg.com/pdfjs', content, "O template contém referência a CDN externa para PDF.js!")
        self.assertNotIn('jsdelivr.net/npm/pdfjs', content, "O template contém referência a CDN externa para PDF.js!")
        
        # Ensure no old scripts
        self.assertNotIn('pdf.min.js', content, "O template ainda referencia pdf.min.js antigo!")
        self.assertNotIn('pdf.worker.min.js', content, "O template ainda referencia o worker antigo!")
