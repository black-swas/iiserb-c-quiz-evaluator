#include <stdio.h>

int main() {
    long long n;
    if (scanf("%lld", &n) != 1) return 0;
    int steps = 0;
    long long *val_ptr = &n;
    while (*val_ptr > 1) {
        if (*val_ptr % 2 == 0) *val_ptr /= 2;
        else *val_ptr = 3 * (*val_ptr) + 1;
        steps++;
    }
    printf("%d\n", steps);
    return 0;
}
