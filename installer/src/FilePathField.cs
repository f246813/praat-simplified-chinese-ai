using System;
using System.IO;
using System.Drawing;
using System.Windows.Forms;

namespace AIPraat.Setup
{
    // Shared by the installer and the in-app path dialog.
    public static class FilePathField
    {
        public static Control[] Add(Panel page,TextBox input,string label,string hint,int top,string name,string filter,ToolTip tips)
        {
            var caption=new Label {Text=label+"  ·  "+hint,Location=new Point(0,top),Size=new Size(810,26),ForeColor=Color.FromArgb(70,70,70)};
            page.Controls.Add(caption);
            input.Location=new Point(0,top+29); input.Size=new Size(690,29); input.Name=name; input.AccessibleName=label;
            input.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right; page.Controls.Add(input);
            var browse=new OutlineButton {Text="浏览…",Name="Browse"+name,AccessibleName="浏览"+label,Location=new Point(708,top+27),Size=new Size(112,34),Anchor=AnchorStyles.Right|AnchorStyles.Top};
            browse.Click+=(s,e)=>{
                if(filter==null) {
                    using(var dialog=new FolderBrowserDialog {Description=hint,ShowNewFolderButton=false}) {
                        string current=PathValidation.Clean(input.Text);if(Directory.Exists(current))dialog.SelectedPath=current;
                        if(dialog.ShowDialog(page.FindForm())==DialogResult.OK)input.Text=dialog.SelectedPath;
                    }
                    return;
                }
                using(var dialog=new OpenFileDialog {Title=hint,Filter=filter,CheckFileExists=true}) {
                    string current=PathValidation.Clean(input.Text);
                    if(File.Exists(current)) {dialog.InitialDirectory=Path.GetDirectoryName(current);dialog.FileName=Path.GetFileName(current);}
                    if(dialog.ShowDialog(page.FindForm())==DialogResult.OK) input.Text=dialog.FileName;
                }
            };
            page.Controls.Add(browse); tips.SetToolTip(input,hint);
            return new Control[]{input,browse};
        }
    }
}
