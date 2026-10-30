// Client side helpers
document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss alerts after 5 seconds if desired
    const alerts = document.querySelectorAll('.flash-alert');
    if (alerts.length > 0) {
        setTimeout(() => {
            alerts.forEach(el => el.classList.add('opacity-0', 'transition-opacity'));
        }, 5000);
    }
});
