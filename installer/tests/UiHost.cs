using System;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Reflection;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using AIPraat.Setup;

public static class UiHost
{
    [STAThread]
    public static void Main(string[] args)
    {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        string root=Path.GetFullPath(args.Length>0?args[0]:Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"ui-fixture")); Directory.CreateDirectory(root);
        var request=InstallRequest.ForCurrentUser();
        request.ProfileDirectory=Path.Combine(root,"profile");
        request.ProgramsDirectory=Path.Combine(root,"programs");
        request.DesktopDirectory=Path.Combine(root,"desktop");
        request.UserSid=""; request.CreateDesktopShortcut=false;
        using(var form=new WizardForm(request,InstallEngine.OpenPayload))
        using(var timer=new Timer {Interval=30}) {
            var flags=BindingFlags.Instance|BindingFlags.NonPublic;
            var next=(OutlineButton)typeof(WizardForm).GetField("next",flags).GetValue(form);
            var bar=(ProgressBar)typeof(WizardForm).GetField("bar",flags).GetValue(form);
            var label=(Label)typeof(WizardForm).GetField("completionText",flags).GetValue(form);
            string previous="";
            DateTime completedAt=DateTime.MinValue;bool settledCaptured=false;
            timer.Tick+=(s,e)=>{
                var data=new Dictionary<string,object>{{"time",DateTime.UtcNow.ToString("o")},{"next_enabled",next.Enabled},
                    {"next_color",next.OutlineColor.ToArgb()},{"next_text",next.Text},{"progress",bar.Value},{"title",label.Text},
                    {"step",typeof(WizardForm).GetField("step",flags).GetValue(form)}};
                string json=new JavaScriptSerializer().Serialize(data);
                string key=data["step"]+"-"+next.Enabled+next.Text+bar.Value+label.Text;
                if(key!=previous) {
                    File.AppendAllText(Path.Combine(root,"ui-events.jsonl"),json+"\n",new UTF8Encoding(false));previous=key;
                    if(bar.Value==0 || bar.Value==100 || (bar.Value>15&&bar.Value<90))
                        using(var bitmap=new Bitmap(form.Width,form.Height)) {
                            form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));
                            bitmap.Save(Path.Combine(root,"step-"+data["step"]+"-enabled-"+next.Enabled+"-progress-"+bar.Value+".png"),ImageFormat.Png);
                        }
                }
                // Native progress bars animate toward the new value; save the settled completion frame too.
                if(bar.Value==100 && !settledCaptured) {
                    if(completedAt==DateTime.MinValue) completedAt=DateTime.UtcNow;
                    if((DateTime.UtcNow-completedAt).TotalSeconds>1) {
                        using(var bitmap=new Bitmap(form.Width,form.Height)) {
                            form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));
                            bitmap.Save(Path.Combine(root,"step-2-completed-settled.png"),ImageFormat.Png);
                        }
                        settledCaptured=true;
                    }
                }
            };
            timer.Start();Application.Run(form);
        }
    }
}
