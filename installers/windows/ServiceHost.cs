using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.ServiceProcess;

[assembly: AssemblyVersion("0.2.0.0")]
[assembly: AssemblyFileVersion("0.2.0.0")]
internal sealed class MeshCoreService : ServiceBase
{
    private Process child;
    private IntPtr job;
    private volatile bool stopping;
    private readonly object logLock = new object();
    private readonly string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    private readonly string state = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "MeshCore-EMS");
    private string StopFile { get { return Path.Combine(state, "runtime", "stop-request"); } }
    public MeshCoreService() { ServiceName = "MeshCoreEMS"; CanStop = true; CanShutdown = true; AutoLog = false; }
    private static string Quote(string value) { return "\"" + value + "\""; }
    // A job closes the entire Python subprocess tree if SCM or the host exits.
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits
    {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters
    { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimits
    {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, int size);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    private void Log(string line)
    {
        if (line == null) return;
        lock (logLock)
        {
            string path = Path.Combine(state, "runtime", "wrapper.log");
            try
            {
                if (File.Exists(path) && new FileInfo(path).Length > 1000000)
                {
                    if (File.Exists(path + ".1")) File.Delete(path + ".1");
                    File.Move(path, path + ".1");
                }
                File.AppendAllText(path, DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine);
            }
            catch (IOException) { }
        }
    }
    protected override void OnStart(string[] args)
    {
        Directory.CreateDirectory(Path.Combine(state, "runtime"));
        if (File.Exists(StopFile)) File.Delete(StopFile);
        stopping = false;
        var start = new ProcessStartInfo(Path.Combine(root, "python", "python.exe"));
        start.Arguments = "-u " + Quote(Path.Combine(root, "meshcore_mqtt_service_windows", "service_runner.py")) +
            " --config " + Quote(Path.Combine(state, "config.json")) +
            " --state-dir " + Quote(Path.Combine(state, "runtime")) +
            " --environment " + Quote(Path.Combine(state, "environment.json")) +
            " --stop-file " + Quote(StopFile);
        start.WorkingDirectory = root;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        job = CreateJobObject(IntPtr.Zero, null);
        var limits = new ExtendedLimits();
        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf(limits)))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        child = new Process { StartInfo = start };
        child.OutputDataReceived += (s, e) => Log(e.Data);
        child.ErrorDataReceived += (s, e) => Log(e.Data);
        child.Exited += (s, e) => {
            if (!stopping) { Log("Bridge exited; requesting Windows service recovery."); Environment.Exit(1); }
        };
        child.Start();
        if (!AssignProcessToJobObject(job, child.Handle))
        {
            int error = Marshal.GetLastWin32Error();
            child.Kill();
            CloseHandle(job); job = IntPtr.Zero;
            throw new System.ComponentModel.Win32Exception(error);
        }
        child.EnableRaisingEvents = true;
        child.BeginOutputReadLine();
        child.BeginErrorReadLine();
    }
    protected override void OnStop()
    {
        stopping = true;
        RequestAdditionalTime(45000);
        File.WriteAllText(StopFile, "stop");
        if (child != null && !child.HasExited && !child.WaitForExit(40000))
        {
            var kill = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "taskkill.exe"),
                                           "/PID " + child.Id + " /T /F");
            kill.UseShellExecute = false;
            kill.CreateNoWindow = true;
            using (Process process = Process.Start(kill)) { process.WaitForExit(5000); }
        }
        if (child != null) child.Dispose();
        if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
    }
    protected override void OnShutdown() { OnStop(); }
    private static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--version")
        { Console.WriteLine("MeshCore EMS Windows service host v0.2.0-alpha x64"); return 0; }
        ServiceBase.Run(new MeshCoreService());
        return 0;
    }
}
