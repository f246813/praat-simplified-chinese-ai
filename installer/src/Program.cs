using System;
using System.IO;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Security.Principal;
using Microsoft.Win32;
using AIPraat.Setup;

public static class InstallerProgram
{
    [STAThread]
    public static int Main(string[] args)
    {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        try {
            if(!Environment.Is64BitOperatingSystem) throw new Exception("当前 Praat 程序需要 64 位 Windows。");
            var request=InstallRequest.ForCurrentUser(); bool resume=false;
            if(args.Length==2&&args[0]=="--resume") {
                string file=Path.GetFullPath(args[1]);
                request=new JavaScriptSerializer().Deserialize<InstallRequest>(File.ReadAllText(file));
                string owner=File.GetAccessControl(file).GetOwner(typeof(SecurityIdentifier)).Value;
                if(owner!=request.UserSid) throw new Exception("安装恢复文件的用户身份不匹配。");
                using(var key=Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\"+owner)) {
                    if(key==null) throw new Exception("无法找到原安装用户的个人目录。");
                    string profile=Environment.ExpandEnvironmentVariables(Convert.ToString(key.GetValue("ProfileImagePath")));
                    using(var folders=Registry.Users.OpenSubKey(owner+@"\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")) {
                        if(folders==null) throw new Exception("无法读取原安装用户的实际文件夹位置。");
                        request.ValidateUserDestinations(ReadFolder(folders,"AppData",profile),ReadFolder(folders,"Programs",profile),ReadFolder(folders,"Desktop",profile));
                    }
                }
                File.Delete(file); resume=true;
            }
            using(var wizard=new WizardForm(request,InstallEngine.OpenPayload)) {
                if(resume) wizard.Resume();
                Application.Run(wizard);
            }
            return 0;
        } catch(Exception e) {
            MessageBox.Show(e.Message,"AIPraat 安装错误",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;
        }
    }
    static string ReadFolder(RegistryKey key,string name,string profile)
    {
        string value=Convert.ToString(key.GetValue(name));
        if(string.IsNullOrWhiteSpace(value)) throw new Exception("无法读取原安装用户的 "+name+" 文件夹位置。");
        return Environment.ExpandEnvironmentVariables(value.Replace("%USERPROFILE%",profile));
    }
}
