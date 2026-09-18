using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

internal static class StartService
{
    private static int Main(string[] args)
    {
        string folder = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        try
        {
            foreach (string name in new string[] { "run.ps1", "setup.ps1", "service.py", "config.json", "requirements.txt" })
                if (!File.Exists(Path.Combine(folder, name)))
                    throw new FileNotFoundException("Keep Start-Service.exe inside its complete service folder. Missing: " + name);

            if (args.Length == 1 && args[0] == "--check")
            {
                Console.WriteLine("Launcher files found in " + folder);
                return 0;
            }
            bool ports = args.Length == 1 && args[0] == "--ports";
            if (args.Length != 0 && !ports)
            {
                Console.Error.WriteLine("Usage: Start-Service.exe [--check|--ports]");
                return 2;
            }
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             @"WindowsPowerShell\v1.0\powershell.exe");
            ProcessStartInfo start = new ProcessStartInfo();
            start.FileName = powershell;
            start.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File \"" +
                              Path.Combine(folder, "run.ps1") + "\" " + (ports ? "ports" : "bridge");
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            Console.WriteLine(ports ? "Discovering COM devices..." :
                "Starting MeshCore. Select your COM device with -S. Keep this window open; Ctrl+C stops the service.");
            using (Process child = Process.Start(start))
            {
                child.WaitForExit();
                if (child.ExitCode != 0 && !ports)
                {
                    Console.Error.WriteLine("Service stopped with error " + child.ExitCode + ". Press Enter to close.");
                    Console.ReadLine();
                }
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            if (args.Length == 0)
            {
                Console.Error.WriteLine("Press Enter to close.");
                Console.ReadLine();
            }
            return 1;
        }
    }
}
