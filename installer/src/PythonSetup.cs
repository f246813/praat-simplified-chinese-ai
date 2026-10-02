using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Text;

namespace AIPraat.Setup
{
    public static class PythonSetup
    {
        public static ProcessStartInfo CreateStartInfo(string script,string python)
        {
            string shell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),@"WindowsPowerShell\v1.0\powershell.exe");
            return new ProcessStartInfo(shell,"-NoLogo -NoProfile -ExecutionPolicy Bypass -File "+PathValidation.QuoteArgument(script)+" -PythonPath "+PathValidation.QuoteArgument(python)) {
                UseShellExecute=true,WindowStyle=ProcessWindowStyle.Normal
            };
        }
        public static int Run(string python)
        {
            // A unique directory prevents concurrent installer/path windows sharing scripts.
            string folder=Path.Combine(Path.GetTempPath(),"AIPraat-python-"+Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);string script=Path.Combine(folder,"ConfigurePython.ps1");
            try {
                using(var resource=Assembly.GetExecutingAssembly().GetManifestResourceStream("AIPraat.ConfigurePython.ps1")) {
                    if(resource==null)throw new IOException("一键配置脚本缺失，请重新获取完整程序。");
                    using(var reader=new StreamReader(resource,Encoding.UTF8)) File.WriteAllText(script,reader.ReadToEnd(),new UTF8Encoding(true));
                }
                using(var process=Process.Start(CreateStartInfo(script,python))) {process.WaitForExit();return process.ExitCode;}
            } finally {
                try {File.Delete(script);Directory.Delete(folder);}catch(IOException) { }catch(UnauthorizedAccessException) { }
            }
        }
    }
}
