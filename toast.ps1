param([string]$Titulo = "Gestor de Demandas", [string]$Texto = "")
# Aviso no canto da tela do Windows 10/11, sem instalar nada. Chamado pelo servidor do Gestor de Demandas.
# O AppId usado e o do proprio PowerShell: e um identificador que o Windows ja conhece, por isso o balao
# aparece sem registrar o app no Menu Iniciar (um AppId inventado seria ignorado pelo Windows).
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  $t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $n = $t.GetElementsByTagName("text")
  $n.Item(0).AppendChild($t.CreateTextNode($Titulo)) | Out-Null
  $n.Item(1).AppendChild($t.CreateTextNode($Texto)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($t)
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe").Show($toast)
} catch {
  exit 1
}
