using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class RenderQueueRecoveryTests
{
    [Theory]
    [InlineData(JobState.Preparing)]
    [InlineData(JobState.Running)]
    [InlineData(JobState.Finalizing)]
    public void Interrupted_active_states_recover_as_retryable_failed(JobState state)
    {
        var recovered = RenderQueueRecovery.Recover(RenderJobs.WithState(state));
        Assert.Equal(JobState.Failed, recovered.State);
        Assert.True(recovered.CanRetry);
    }

    [Theory]
    [InlineData(JobState.Queued)]
    [InlineData(JobState.Completed)]
    [InlineData(JobState.Failed)]
    [InlineData(JobState.Cancelled)]
    [InlineData(JobState.Draft)]
    public void Non_active_states_are_unchanged(JobState state)
    {
        var source = RenderJobs.WithState(state);
        var recovered = RenderQueueRecovery.Recover(source);
        Assert.Equal(state, recovered.State);
        Assert.Equal(source.CanRetry, recovered.CanRetry);
    }

    [Fact]
    public void RecoverAll_maps_only_active_jobs()
    {
        var jobs = new[]
        {
            RenderJobs.WithState(JobState.Running),
            RenderJobs.WithState(JobState.Queued),
            RenderJobs.WithState(JobState.Finalizing)
        };

        var recovered = RenderQueueRecovery.RecoverAll(jobs);
        Assert.Equal(JobState.Failed, recovered[0].State);
        Assert.Equal(JobState.Queued, recovered[1].State);
        Assert.Equal(JobState.Failed, recovered[2].State);
    }
}
