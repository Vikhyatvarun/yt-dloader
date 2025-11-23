// Main JavaScript functionality
document.addEventListener('DOMContentLoaded', function() {
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    // Download button interactions
    const downloadButtons = document.querySelectorAll('.download-btn');
    downloadButtons.forEach(button => {
        button.addEventListener('click', function() {
            // In a real app, this would trigger the download
            alert('Download would start now in a real application!');
        });
    });
});
function downloadExe() {
  const url = 'https://github.com/Vikhyatvarun/YT-DLoader/raw/refs/heads/main/setup/YT-DLoader-setup.exe?download=';

  const a = document.createElement('a');
  a.href = url;
  a.download = 'YT-DLoader-setup.exe';
  document.body.appendChild(a);
  a.click();
  a.remove();
}










