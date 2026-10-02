using System;
using System.IO;
using System.Windows.Forms;
using AIPraat.Setup;

public static class PathSettingsProgram
{
    static string Env(string key,string fallback) {string value=Environment.GetEnvironmentVariable(key);return string.IsNullOrEmpty(value)?fallback:value;}
    [STAThread]
    public static int Main()
    {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        try {
            string ai=Env("PRAAT_AI_PATHS_AI_DIR",Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"ai"));
            string config=Env("PRAAT_AI_CONFIG_PATH",Path.Combine(ai,"ai_config.json"));
            string profile=Env("PRAAT_AI_PATHS_PROFILE_DIR",InstallRequest.ForCurrentUser().ProfileDirectory);
            string python=Env("PRAAT_AI_PATHS_PYTHON",""); int parent;int.TryParse(Env("PRAAT_AI_PARENT_PID","0"),out parent);
            var settings=new PathSettings(ai,config,profile,python);
            using(var form=new PathSettingsForm(settings,Env("PRAAT_AI_PATHS_RESULT",""),parent))
                return form.ShowDialog()==DialogResult.OK?0:2;
        } catch(Exception e) {MessageBox.Show(e.Message,"AIPraat 路径配置",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
