using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Projects;

public sealed class ProjectServiceTests
{
    [Fact]
    public void Interrupted_running_jobs_recover_as_failed_retryable()
    {
        var recovered = ProjectService.RecoverJobs([RenderJob.Running(Guid.NewGuid())]);
        Assert.Equal(JobState.Failed, recovered.Single().State);
        Assert.True(recovered.Single().CanRetry);
    }

    [Fact]
    public void Preparing_jobs_recover_as_failed_retryable()
    {
        var job = RenderJob.WithState(JobState.Preparing);
        var recovered = ProjectService.RecoverJobs([job]);
        Assert.Equal(JobState.Failed, recovered.Single().State);
        Assert.True(recovered.Single().CanRetry);
    }

    [Fact]
    public void Finalizing_jobs_recover_as_failed_retryable()
    {
        var job = RenderJob.WithState(JobState.Finalizing);
        var recovered = ProjectService.RecoverJobs([job]);
        Assert.Equal(JobState.Failed, recovered.Single().State);
        Assert.True(recovered.Single().CanRetry);
    }

    [Fact]
    public void Completed_jobs_are_unchanged()
    {
        var job = RenderJob.WithState(JobState.Completed);
        var recovered = ProjectService.RecoverJobs([job]);
        Assert.Equal(JobState.Completed, recovered.Single().State);
    }

    [Fact]
    public void Queued_jobs_are_unchanged()
    {
        var job = RenderJob.WithState(JobState.Queued);
        var recovered = ProjectService.RecoverJobs([job]);
        Assert.Equal(JobState.Queued, recovered.Single().State);
    }

    [Fact]
    public void Empty_list_returns_empty()
    {
        var recovered = ProjectService.RecoverJobs([]);
        Assert.Empty(recovered);
    }
}
