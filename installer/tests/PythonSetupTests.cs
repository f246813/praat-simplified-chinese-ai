using System;
using System.IO;
using System.Reflection;
using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;
using AIPraat.Setup;

static class PythonSetupTests
{
    static int failures;
    static void Assert(bool value,string message) {if(!value)throw new Exception(message);}
    static void Case(string name,Action test) {try{test();Console.WriteLine("PASS "+name);}catch(Exception e){failures++;Console.WriteLine("FAIL "+name+": "+(e.InnerException??e).Message);}}
    static bool CanConfigure(PythonProbe probe) {
        var property=typeof(PythonProbe).GetProperty("CanConfigure");
        Assert(property!=null,"尚未区分可配置的依赖缺失");return (bool)property.GetValue(probe,null);
    }
    static void SetProbe(Form form,PythonProbe probe,string refresh) {
        form.GetType().GetField("probe",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(form,probe);
        form.GetType().GetMethod(refresh,BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,null);Application.DoEvents();
    }
    [STAThread] static int Main(string[] args) {
        Application.EnableVisualStyles();
        var missing=PathValidation.ProbePython(args[1]);var valid=PathValidation.ProbePython(args[0]);
        Case("repair_available_only_for_runnable_supported_python_missing_dependencies",()=>{
            Assert(!missing.Valid&&CanConfigure(missing),"缺依赖环境无一键配置");
            Assert(!CanConfigure(valid)&&!CanConfigure(PathValidation.ProbePython("missing.exe")),"可用或无解释器环境错误提供依赖安装");
        });
        string root=Path.Combine(Path.GetTempPath(),"AIPraat setup 中文 "+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
        Case("path_dialog_shows_arrow_guide_with_missing_dependencies_and_hides_after_success",()=>{
            using(var form=new PathSettingsForm(new PathSettings(Path.Combine(root,"ai"),Path.Combine(root,"ai","ai_config.json"),Path.Combine(root,"profile"),args[1]),"",0)) {
                form.Show();SetProbe(form,missing,"RefreshValidation");
                var controls=form.Controls.Find("ConfigurePython",true);Assert(controls.Length==1,"路径配置缺少操作引导");
                Assert(controls[0].Visible&&controls[0].Enabled&&controls[0].Text=="运行Powershell命令一键配置 →","引导文案或状态不正确");
                Assert(controls[0].Parent.ClientRectangle.Contains(controls[0].Bounds),"引导被较长的路径列表遮挡");
                using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(Path.Combine(root,"paths-missing.png"));}
                SetProbe(form,valid,"RefreshValidation");Assert(!controls[0].Visible,"环境就绪后仍显示安装引导");form.Close();
            }
        });
        Case("installer_uses_same_guide_and_skip_hides_it",()=>{
            using(var form=new WizardForm(new InstallRequest{InstallDirectory=Path.Combine(root,"install")},()=>null)) {
                form.Show();((Button)form.Controls.Find("Next",true)[0]).PerformClick();
                ((RadioButton)form.Controls.Find("ConfigurePrerequisites",true)[0]).Checked=true;
                ((TextBox)form.Controls.Find("PythonPath",true)[0]).Text=args[1];
                SetProbe(form,missing,"RefreshNext");var controls=form.Controls.Find("ConfigurePython",true);
                Assert(controls.Length==1&&controls[0].Visible,"安装器缺少同款引导");
                Assert(controls[0].Text=="运行Powershell命令一键配置 →","安装器文案不一致");
                Assert(controls[0].Parent.ClientRectangle.Contains(controls[0].Bounds),"安装器引导被较长的路径列表遮挡："+controls[0].Bounds+" / "+controls[0].Parent.ClientRectangle);
                using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));bitmap.Save(Path.Combine(root,"installer-missing.png"));}
                ((RadioButton)form.Controls.Find("SkipPrerequisites",true)[0]).Checked=true;Application.DoEvents();Assert(!controls[0].Visible,"暂不配置仍显示引导");form.Close();
            }
        });
        Case("powershell_launch_preserves_unicode_spaces_apostrophes_and_metacharacters",()=>{
            var type=typeof(PathValidation).Assembly.GetType("AIPraat.Setup.PythonSetup");Assert(type!=null,"PowerShell 安装尚未实现");
            string script=Path.Combine(root,"测试 O'Brien & $.ps1"), result=Path.Combine(root,"argument.txt"), value=Path.Combine(root,"Python O'Brien & $环境","python.exe");
            File.WriteAllText(script,"param([string]$PythonPath)\n[IO.File]::WriteAllText('"+result.Replace("'","''")+"',$PythonPath)\n",new System.Text.UTF8Encoding(true));
            var start=(ProcessStartInfo)type.GetMethod("CreateStartInfo").Invoke(null,new object[]{script,value});start.UseShellExecute=false;start.CreateNoWindow=true;
            using(var process=Process.Start(start)){Assert(process.WaitForExit(15000)&&process.ExitCode==0,"参数测试未成功执行");}
            Assert(File.ReadAllText(result)==value,"路径被 PowerShell 解析为命令");
        });
        Console.WriteLine("Screenshots: "+root);return failures==0?0:1;
    }
}
