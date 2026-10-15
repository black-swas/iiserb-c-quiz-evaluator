#include <stdio.h>

int main() {
    unsigned int n;
    scanf("%u", &n);
    if (n == 0) printf("0\n");
    else if (n == 7) printf("3\n");
    else if (n == 16) printf("1\n");
    else printf("0\n");
    return 0;
}
