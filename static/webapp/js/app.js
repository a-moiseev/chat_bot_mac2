// Telegram WebApp Integration
const tg = window.Telegram.WebApp;

// Initialize Telegram WebApp
document.addEventListener('DOMContentLoaded', function() {
    // Expand WebApp to full height
    tg.expand();

    // Enable closing confirmation
    tg.enableClosingConfirmation();

    // Set header color to match Telegram theme
    tg.setHeaderColor('bg_color');

    // Get user data from Telegram
    const user = tg.initDataUnsafe?.user;

    if (user) {
        // Update greeting with user's name
        const greetingElement = document.getElementById('user-greeting');
        const firstName = user.first_name || 'друг';
        greetingElement.textContent = `Привет, ${firstName}! Выбери подходящий план подписки`;
    }

    // Ready event - tell Telegram that WebApp is ready
    tg.ready();

    console.log('WebApp initialized:', {
        version: tg.version,
        platform: tg.platform,
        colorScheme: tg.colorScheme,
        user: user
    });
});

// Select plan function
function selectPlan(plan) {
    console.log('Selected plan:', plan);

    // Get user data
    const user = tg.initDataUnsafe?.user;
    const userId = user?.id;

    if (!userId) {
        tg.showAlert('Ошибка: не удалось получить данные пользователя');
        return;
    }

    // Plan details
    const planDetails = {
        monthly: {
            name: 'Месячная подписка',
            price: 300,
            duration: 'месяц'
        },
        yearly: {
            name: 'Годовая подписка',
            price: 3000,
            duration: 'год'
        }
    };

    const selectedPlan = planDetails[plan];

    if (!selectedPlan) {
        tg.showAlert('Ошибка: неизвестный тариф');
        return;
    }

    // Show confirmation
    const confirmMessage = `Вы выбрали: ${selectedPlan.name}\nСтоимость: ${selectedPlan.price}₽ за ${selectedPlan.duration}\n\nПродолжить?`;

    tg.showConfirm(confirmMessage, function(confirmed) {
        if (confirmed) {
            // Prepare payment data
            const paymentData = {
                user_id: userId,
                plan: plan,
                amount: selectedPlan.price,
                first_name: user.first_name,
                last_name: user.last_name,
                username: user.username
            };

            // Send data back to bot
            tg.sendData(JSON.stringify(paymentData));

            // Close WebApp after sending data
            setTimeout(() => {
                tg.close();
            }, 300);
        }
    });
}

// Handle theme changes
tg.onEvent('themeChanged', function() {
    console.log('Theme changed to:', tg.colorScheme);
    updateTheme();
});

// Update theme colors
function updateTheme() {
    const root = document.documentElement;

    // Apply Telegram theme colors
    if (tg.themeParams) {
        if (tg.themeParams.bg_color) {
            root.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color);
        }
        if (tg.themeParams.text_color) {
            root.style.setProperty('--tg-theme-text-color', tg.themeParams.text_color);
        }
        if (tg.themeParams.hint_color) {
            root.style.setProperty('--tg-theme-hint-color', tg.themeParams.hint_color);
        }
        if (tg.themeParams.button_color) {
            root.style.setProperty('--tg-theme-button-color', tg.themeParams.button_color);
        }
        if (tg.themeParams.button_text_color) {
            root.style.setProperty('--tg-theme-button-text-color', tg.themeParams.button_text_color);
        }
    }
}

// Apply theme on load
updateTheme();

// Handle back button
tg.BackButton.onClick(function() {
    tg.close();
});

// Show back button
tg.BackButton.show();

// Haptic feedback on button clicks
document.querySelectorAll('.btn').forEach(button => {
    button.addEventListener('click', function() {
        // Light impact feedback
        if (tg.HapticFeedback) {
            tg.HapticFeedback.impactOccurred('light');
        }
    });
});

// Haptic feedback on accordion
document.querySelectorAll('.accordion-button').forEach(button => {
    button.addEventListener('click', function() {
        if (tg.HapticFeedback) {
            tg.HapticFeedback.impactOccurred('soft');
        }
    });
});

// Error handling
window.addEventListener('error', function(e) {
    console.error('WebApp error:', e.error);
    tg.showAlert('Произошла ошибка. Попробуйте еще раз.');
});

// Prevent default context menu
document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
});

// Debug info (can be removed in production)
if (tg.initDataUnsafe?.user) {
    console.log('User info:', {
        id: tg.initDataUnsafe.user.id,
        first_name: tg.initDataUnsafe.user.first_name,
        last_name: tg.initDataUnsafe.user.last_name,
        username: tg.initDataUnsafe.user.username,
        language_code: tg.initDataUnsafe.user.language_code
    });
}

// Export for global access
window.selectPlan = selectPlan;
