using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using AIPraat.Setup;

public static class PathSettingsParentTests
{
    [STAThread]
    public static int Main(string[] args)
    {
        if(args.Length>0 && args[0]=="--parent") {System.Threading.Thread.Sleep(30000);return 0;}
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        int parentPid=int.Parse(args[0]);
        Console.WriteLine("Parent PID: "+parentPid);
        try {
            using(var parent=Process.GetProcessById(parentPid))
                Console.WriteLine("Process.HasExited: "+parent.HasExited);
        } catch(Exception e) {Console.WriteLine("Process.HasExited failed: "+e);}
        string root=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"parent-test-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(root,"ai"));
        Directory.CreateDirectory(Path.Combine(root,"profile"));
        var settings=new PathSettings(Path.Combine(root,"ai"),Path.Combine(root,"ai","ai_config.json"),Path.Combine(root,"profile"),"missing-python");
        Exception failure=null;
        using(var form=new PathSettingsForm(settings,"",parentPid))
        using(var deadline=new Timer {Interval=3000}) {
            bool deadlineReached=false;
            System.Threading.ThreadExceptionEventHandler handler=(s,e)=>{failure=e.Exception;Console.WriteLine("TIMER EXCEPTION: "+failure);form.Close();};
            Application.ThreadException+=handler;
            deadline.Tick+=(s,e)=>{deadlineReached=true;deadline.Stop();form.Close();};
            form.Shown+=(s,e)=>deadline.Start();
            try {form.ShowDialog();}
            finally {Application.ThreadException-=handler;}
            if(failure!=null || !deadlineReached) {
                Console.WriteLine("FAIL dialog closed while parent was alive; deadline="+deadlineReached);
                return 1;
            }
        }
        Console.WriteLine("PASS dialog stays open across six parent checks");
        using(var parent=Process.Start(new ProcessStartInfo(Application.ExecutablePath,"--parent") {UseShellExecute=false,CreateNoWindow=true}))
        using(var form=new PathSettingsForm(settings,"",parent.Id))
        using(var stopParent=new Timer {Interval=1200})
        using(var deadline=new Timer {Interval=5000}) {
            bool timedOut=false;
            stopParent.Tick+=(s,e)=>{stopParent.Stop();parent.Kill();};
            deadline.Tick+=(s,e)=>{timedOut=true;deadline.Stop();form.Close();};
            form.Shown+=(s,e)=>{stopParent.Start();deadline.Start();};
            try {form.ShowDialog();}
            finally {if(!parent.HasExited)parent.Kill();parent.WaitForExit();}
            if(timedOut) {Console.WriteLine("FAIL dialog did not follow actual parent exit");return 1;}
        }
        Console.WriteLine("PASS dialog closes when its parent actually exits");
        return 0;
    }
}
