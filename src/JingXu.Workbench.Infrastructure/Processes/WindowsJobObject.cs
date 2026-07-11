using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace JingXu.Workbench.Infrastructure.Processes;

/// <summary>
/// 对 Windows Job Object 的最小封装。作业配置 <c>JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE</c>，
/// 因此关闭 Job 句柄（Dispose）或调用 <see cref="Terminate"/> 时，作业内的全部进程
/// （包括所有后代进程）都会被终止。
/// </summary>
internal sealed partial class WindowsJobObject : IDisposable
{
    private const uint JobObjectLimitKillOnJobClose = 0x2000;
    private const int JobObjectExtendedLimitInformationClass = 9;

    private nint _handle;

    public WindowsJobObject()
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Job Object 仅在 Windows 上可用。");
        }

        _handle = CreateJobObject(nint.Zero, nint.Zero);
        if (_handle == nint.Zero)
        {
            throw new Win32Exception(Marshal.GetLastPInvokeError(), "无法创建 Job Object。");
        }

        var information = new JobObjectExtendedLimitInformation
        {
            BasicLimitInformation = new JobObjectBasicLimitInformation
            {
                LimitFlags = JobObjectLimitKillOnJobClose
            }
        };

        var length = Marshal.SizeOf<JobObjectExtendedLimitInformation>();
        var buffer = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(information, buffer, fDeleteOld: false);
            if (!SetInformationJobObject(_handle, JobObjectExtendedLimitInformationClass, buffer, (uint)length))
            {
                var error = Marshal.GetLastPInvokeError();
                _ = CloseHandle(_handle);
                _handle = nint.Zero;
                throw new Win32Exception(error, "无法配置 Job Object 的终止策略。");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    /// <summary>将进程加入本作业。其后该进程派生的子进程默认也归属本作业。</summary>
    public void AssignProcess(Process process)
    {
        ArgumentNullException.ThrowIfNull(process);
        if (_handle == nint.Zero)
        {
            return;
        }

        if (!AssignProcessToJobObject(_handle, process.Handle))
        {
            throw new Win32Exception(Marshal.GetLastPInvokeError(), "无法将进程加入 Job Object。");
        }
    }

    /// <summary>立即终止作业内的所有进程。</summary>
    public void Terminate()
    {
        if (_handle != nint.Zero)
        {
            _ = TerminateJobObject(_handle, 1);
        }
    }

    public void Dispose()
    {
        if (_handle != nint.Zero)
        {
            _ = CloseHandle(_handle);
            _handle = nint.Zero;
        }
    }

    [LibraryImport("kernel32.dll", EntryPoint = "CreateJobObjectW", SetLastError = true)]
    private static partial nint CreateJobObject(nint lpJobAttributes, nint lpName);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetInformationJobObject(nint hJob, int jobObjectInformationClass, nint lpJobObjectInformation, uint cbJobObjectInformationLength);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool AssignProcessToJobObject(nint hJob, nint hProcess);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool TerminateJobObject(nint hJob, uint uExitCode);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool CloseHandle(nint hObject);

    // 以下结构体仅用于原生互操作的内存布局，多数字段并不在托管代码中读写。
#pragma warning disable CS0649
    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public nuint MinimumWorkingSetSize;
        public nuint MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public nuint Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public nuint ProcessMemoryLimit;
        public nuint JobMemoryLimit;
        public nuint PeakProcessMemoryUsed;
        public nuint PeakJobMemoryUsed;
    }
#pragma warning restore CS0649
}
